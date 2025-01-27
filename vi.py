import sys
import os
from datetime import datetime
import time
import hashlib
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLineEdit, QPushButton, QLabel, 
                            QProgressBar, QTextEdit, QFileDialog, QMessageBox,
                            QCheckBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from instagrapi import Client
import requests
import json

class MediaTracker:
    def __init__(self, file_path="downloaded_media.json"):
        self.file_path = file_path
        self.downloaded_media = self.load_downloaded_media()

    def load_downloaded_media(self):
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, 'r') as f:
                    return json.load(f)
            return {}
        except Exception:
            return {}

    def save_downloaded_media(self):
        try:
            with open(self.file_path, 'w') as f:
                json.dump(self.downloaded_media, f)
        except Exception as e:
            print(f"Error saving media tracker: {e}")

    def is_media_downloaded(self, media_id, media_url):
        media_hash = hashlib.md5(media_url.encode()).hexdigest()
        return media_hash in self.downloaded_media

    def add_media(self, media_id, media_url):
        media_hash = hashlib.md5(media_url.encode()).hexdigest()
        self.downloaded_media[media_hash] = {
            'media_id': media_id,
            'downloaded_at': datetime.now().isoformat()
        }
        self.save_downloaded_media()

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

    def download_media(self, url, filename):
        try:
            if self.media_tracker.is_media_downloaded(filename, url):
                self.progress_updated.emit(f"Medya zaten indirilmiş: {os.path.basename(filename)}")
                return False

            response = requests.get(url, stream=True)
            if response.status_code == 200:
                with open(filename, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=1024):
                        if chunk:
                            f.write(chunk)
                self.media_tracker.add_media(filename, url)
                return True
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

            downloaded_count = 0
            skipped_count = 0
            for media in medias:
                if not self.is_running:
                    break

                try:
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    
                    if media.media_type == 1 and self.download_photos:  # Photo
                        url = media.thumbnail_url
                        ext = '.jpg'
                    elif media.media_type == 2 and self.download_videos:  # Video
                        url = media.video_url
                        ext = '.mp4'
                    else:
                        continue

                    filename = os.path.join(
                        self.download_path,
                        f"{self.hashtag}_{timestamp}_{downloaded_count}{ext}"
                    )

                    if self.download_media(url, filename):
                        downloaded_count += 1
                        self.progress_count.emit(downloaded_count)
                        self.progress_updated.emit(f"İndirilen medya {downloaded_count}: {os.path.basename(filename)}")
                    else:
                        skipped_count += 1
                    
                    time.sleep(1)  # Rate limiting

                except Exception as e:
                    self.download_error.emit(f"Medya işleme hatası: {str(e)}")
                    continue

            self.download_complete.emit(
                f"Toplam {downloaded_count} medya indirildi, {skipped_count} medya atlandı.")

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

    def initUI(self):
        self.setWindowTitle('Instagram Hashtag İndirici')
        self.setGeometry(100, 100, 600, 500)

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
        self.download_button = QPushButton('İndirmeyi Başlat')
        self.download_button.clicked.connect(self.start_download)
        layout.addWidget(self.download_button)

        self.stop_button = QPushButton('İndirmeyi Durdur')
        self.stop_button.clicked.connect(self.stop_download)
        self.stop_button.setEnabled(False)
        layout.addWidget(self.stop_button)

        # İlerleme çubuğu
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        # Log alanı
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        self.statusBar().showMessage('Hazır')

    def select_download_path(self):
        folder = QFileDialog.getExistingDirectory(self, 'İndirme Klasörünü Seç')
        if folder:
            self.path_input.setText(folder)

    def log_message(self, message):
        self.log_text.append(f"{datetime.now().strftime('%H:%M:%S')}: {message}")

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
        except ValueError:
            QMessageBox.warning(self, 'Hata', 'Geçerli bir sayı girin.')
            return

        self.download_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress_bar.setValue(0)

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
        QMessageBox.information(self, 'Tamamlandı', message)

    def update_progress(self, count):
        if self.limit_input.text().strip():
            limit = int(self.limit_input.text())
            progress = (count / limit) * 100
            self.progress_bar.setValue(int(progress))

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

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    ex = InstagramDownloaderGUI()
    ex.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()