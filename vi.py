import sys
import os
from datetime import datetime
import time
import hashlib
import json
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLineEdit, QPushButton, QLabel, 
                            QProgressBar, QTextEdit, QFileDialog, QMessageBox,
                            QCheckBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from instagrapi import Client
import requests
import logging

# Logging ayarları
logging.basicConfig(
    filename='instagram_downloader.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class MediaTracker:
    def __init__(self, file_path="downloaded_media.json"):
        self.file_path = file_path
        self.downloaded_media = self.load_downloaded_media()

    def load_downloaded_media(self):
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            logging.error(f"MediaTracker yükleme hatası: {e}")
            return {}

    def save_downloaded_media(self):
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(self.downloaded_media, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"MediaTracker kaydetme hatası: {e}")

    def is_media_downloaded(self, media_id, media_url):
        try:
            media_url_str = str(media_url)
            media_hash = hashlib.md5(media_url_str.encode('utf-8')).hexdigest()
            return media_hash in self.downloaded_media
        except Exception as e:
            logging.error(f"Medya kontrol hatası: {e}")
            return False

    def add_media(self, media_id, media_url):
        try:
            media_url_str = str(media_url)
            media_hash = hashlib.md5(media_url_str.encode('utf-8')).hexdigest()
            self.downloaded_media[media_hash] = {
                'media_id': media_id,
                'url': media_url_str,
                'downloaded_at': datetime.now().isoformat()
            }
            self.save_downloaded_media()
        except Exception as e:
            logging.error(f"Medya ekleme hatası: {e}")

class InstagramDownloaderThread(QThread):
    progress_updated = pyqtSignal(str)
    download_complete = pyqtSignal(str)
    download_error = pyqtSignal(str)
    progress_count = pyqtSignal(int)

    def __init__(self, hashtag, download_path, limit=None, username="", password="", 
                 download_photos=True, download_videos=True):
        super().__init__()
        self.hashtag = hashtag
        self.download_path = download_path
        self.limit = limit
        self.username = username
        self.password = password
        self.is_running = True
        self.client = Client()
        self.download_photos = download_photos
        self.download_videos = download_videos
        self.media_tracker = MediaTracker()

    def download_media(self, url, filename, media_id):
        try:
            url_str = str(url)
            
            if self.media_tracker.is_media_downloaded(media_id, url_str):
                self.progress_updated.emit(f"Medya zaten indirilmiş: {os.path.basename(filename)}")
                return False

            response = requests.get(url_str, stream=True, timeout=30)
            response.raise_for_status()

            with open(filename, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if not self.is_running:
                        f.close()
                        os.remove(filename)
                        return False
                    if chunk:
                        f.write(chunk)

            self.media_tracker.add_media(media_id, url_str)
            return True

        except requests.exceptions.RequestException as e:
            self.download_error.emit(f"İndirme ağ hatası: {str(e)}")
            return False
        except Exception as e:
            self.download_error.emit(f"İndirme hatası: {str(e)}")
            return False

    def run(self):
        try:
            self.progress_updated.emit("Instagram'a giriş yapılıyor...")
            self.client.login(self.username, self.password)
            self.progress_updated.emit("Giriş başarılı!")

            self.progress_updated.emit(f"#{self.hashtag} için medyalar aranıyor...")
            medias = self.client.hashtag_medias_top(self.hashtag, amount=self.limit or 20)

            if not medias:
                self.download_error.emit("Hashtag için medya bulunamadı!")
                return

            downloaded_count = 0
            skipped_count = 0
            total_count = len(medias)

            self.progress_updated.emit(f"Toplam {total_count} medya bulundu")

            for index, media in enumerate(medias):
                if not self.is_running:
                    break

                try:
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    media_id = str(media.id)

                    if media.media_type == 1 and self.download_photos:  # Photo
                        url = str(media.thumbnail_url)
                        ext = '.jpg'
                    elif media.media_type == 2 and self.download_videos:  # Video
                        url = str(media.video_url)
                        ext = '.mp4'
                    else:
                        continue

                    if not url:
                        self.download_error.emit(f"Geçersiz URL: Medya {index + 1} atlanıyor")
                        skipped_count += 1
                        continue

                    filename = os.path.join(
                        self.download_path,
                        f"{self.hashtag}_{timestamp}_{media_id}{ext}"
                    )

                    if self.download_media(url, filename, media_id):
                        downloaded_count += 1
                        self.progress_count.emit(downloaded_count)
                        self.progress_updated.emit(
                            f"İndirilen medya {downloaded_count}/{total_count}: "
                            f"{os.path.basename(filename)}"
                        )
                    else:
                        skipped_count += 1

                    # Rate limiting
                    time.sleep(2)

                except Exception as e:
                    self.download_error.emit(f"Medya işleme hatası: {str(e)}")
                    skipped_count += 1
                    continue

            final_message = (
                f"İndirme tamamlandı!\n"
                f"İndirilen: {downloaded_count}\n"
                f"Atlanan: {skipped_count}\n"
                f"Toplam: {total_count}"
            )
            self.download_complete.emit(final_message)

        except Exception as e:
            self.download_error.emit(f"Genel hata: {str(e)}")
        finally:
            try:
                self.client.logout()
            except:
                pass

    def stop(self):
        self.is_running = False

class InstagramDownloaderGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.downloader_thread = None
        self.last_download_path = ""
        self.load_last_path()

    def initUI(self):
        self.setWindowTitle('Instagram Hashtag İndirici')
        self.setGeometry(100, 100, 800, 600)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Kullanıcı girişi
        login_group = QVBoxLayout()
        
        username_layout = QHBoxLayout()
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText('Instagram kullanıcı adı')
        username_layout.addWidget(QLabel('Kullanıcı Adı:'))
        username_layout.addWidget(self.username_input)
        login_group.addLayout(username_layout)

        password_layout = QHBoxLayout()
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText('Instagram şifresi')
        self.password_input.setEchoMode(QLineEdit.Password)
        password_layout.addWidget(QLabel('Şifre:'))
        password_layout.addWidget(self.password_input)
        login_group.addLayout(password_layout)

        layout.addLayout(login_group)

        # Medya türü seçimi
        media_type_layout = QHBoxLayout()
        self.photo_checkbox = QCheckBox('Fotoğrafları İndir')
        self.video_checkbox = QCheckBox('Videoları İndir')
        self.photo_checkbox.setChecked(True)
        self.video_checkbox.setChecked(True)
        media_type_layout.addWidget(self.photo_checkbox)
        media_type_layout.addWidget(self.video_checkbox)
        layout.addLayout(media_type_layout)

        # Hashtag girişi
        hashtag_layout = QHBoxLayout()
        self.hashtag_input = QLineEdit()
        self.hashtag_input.setPlaceholderText('Hashtag girin (# olmadan)')
        hashtag_layout.addWidget(QLabel('Hashtag:'))
        hashtag_layout.addWidget(self.hashtag_input)
        layout.addLayout(hashtag_layout)

        # Limit girişi
        limit_layout = QHBoxLayout()
        self.limit_input = QLineEdit()
        self.limit_input.setPlaceholderText('Boş bırakın veya sayı girin')
        limit_layout.addWidget(QLabel('Medya Limiti:'))
        limit_layout.addWidget(self.limit_input)
        layout.addLayout(limit_layout)

        # Kayıt yeri seçimi
        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setReadOnly(True)
        self.path_button = QPushButton('Kayıt Yeri Seç')
        self.path_button.clicked.connect(self.select_download_path)
        path_layout.addWidget(self.path_input)
        path_layout.addWidget(self.path_button)
        layout.addLayout(path_layout)

        # Butonlar
        button_layout = QHBoxLayout()
        self.download_button = QPushButton('İndirmeyi Başlat')
        self.download_button.clicked.connect(self.start_download)
        button_layout.addWidget(self.download_button)

        self.stop_button = QPushButton('İndirmeyi Durdur')
        self.stop_button.clicked.connect(self.stop_download)
        self.stop_button.setEnabled(False)
        button_layout.addWidget(self.stop_button)
        layout.addLayout(button_layout)

        # İlerleme çubuğu
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        # Log alanı
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        self.statusBar().showMessage('Hazır')

    def load_last_path(self):
        try:
            if os.path.exists('settings.json'):
                with open('settings.json', 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    last_path = settings.get('last_download_path', '')
                    if os.path.exists(last_path):
                        self.last_download_path = last_path
                        self.path_input.setText(last_path)
        except Exception as e:
            logging.error(f"Ayarları yükleme hatası: {e}")

    def save_last_path(self):
        try:
            settings = {'last_download_path': self.last_download_path}
            with open('settings.json', 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Ayarları kaydetme hatası: {e}")

    def select_download_path(self):
        folder = QFileDialog.getExistingDirectory(
            self, 
            'İndirme Klasörünü Seç',
            self.last_download_path or os.path.expanduser('~')
        )
        if folder:
            self.last_download_path = folder
            self.path_input.setText(folder)
            self.save_last_path()

    def log_message(self, message):
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.log_text.append(f"[{timestamp}] {message}")
        logging.info(message)

    def validate_inputs(self):
        if not self.username_input.text().strip():
            QMessageBox.warning(self, 'Hata', 'Kullanıcı adı gereklidir.')
            return False
            
        if not self.password_input.text().strip():
            QMessageBox.warning(self, 'Hata', 'Şifre gereklidir.')
            return False

        if not self.hashtag_input.text().strip():
            QMessageBox.warning(self, 'Hata', 'Hashtag gereklidir.')
            return False

        if not self.path_input.text().strip():
            QMessageBox.warning(self, 'Hata', 'İndirme klasörü seçilmelidir.')
            return False

        if not self.photo_checkbox.isChecked() and not self.video_checkbox.isChecked():
            QMessageBox.warning(self, 'Hata', 'En az bir medya türü seçilmelidir.')
            return False

        return True

    def start_download(self):
        if not self.validate_inputs():
            return

        hashtag = self.hashtag_input.text().strip()
        download_path = self.path_input.text().strip()
        limit_text = self.limit_input.text().strip()
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()

        try:
            limit = int(limit_text) if limit_text else None
            if limit is not None and limit <= 0:
                raise ValueError("Limit pozitif olmalıdır")
        except ValueError as e:
            QMessageBox.warning(self, 'Hata', f'Geçersiz limit: {str(e)}')
            return

        self.download_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log_text.clear()
        self.log_message("İndirme başlatılıyor...")

        self.downloader_thread = InstagramDownloaderThread(
            hashtag=hashtag,
            download_path=download_path,
            limit=limit,
            username=username,
            password=password,
            download_photos=self.photo_checkbox.isChecked(),
            download_videos=self.video_checkbox.isChecked()
        )

        self.downloader_thread.progress_updated.connect(self.log_message)
        self.downloader_thread.download_complete.connect(self.download_finished)
        self.downloader_thread.download_error.connect(self.log_message)
        self.downloader_thread.progress_count.connect(self.update_progress)
        self.downloader_thread.start()

    def stop_download(self):
        if self.downloader_thread and self.downloader_thread.isRunning():
            self.downloader_thread.stop()
            self.log_message("İndirme durduruldu...")
            self.stop_button.setEnabled(False)
            self.download_button.setEnabled(True)

    def download_finished(self, message):
        self.log_message(message)
        self.download_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.statusBar().showMessage('İndirme tamamlandı')
        self.progress_bar.setValue(100)
        QMessageBox.information(self, 'Tamamlandı', message)

    def update_progress(self, count):
        if self.limit_input.text().strip():
            try:
                limit = int(self.limit_input.text())
                progress = min(int((count / limit) * 100), 100)
                self.progress_bar.setValue(progress)
            except ValueError:
                pass

    def closeEvent(self, event):
        if self.downloader_thread and self.downloader_thread.isRunning():
            reply = QMessageBox.question(
                self, 'Çıkış',
                'İndirme işlemi devam ediyor. Çıkmak istediğinizden emin misiniz?',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.stop_download()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    ex = InstagramDownloaderGUI()
    ex.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()