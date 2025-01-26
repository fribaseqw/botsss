import sys
import os
import time
import json
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLineEdit, QPushButton, QLabel, 
                            QProgressBar, QTextEdit, QMessageBox, QDialog)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
import instaloader
from instaloader.exceptions import LoginRequiredException, BadCredentialsException

class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Instagram Giriş')
        self.setModal(True)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        self.setStyleSheet("""
            QDialog {
                background-color: #fafafa;
            }
            QLineEdit {
                padding: 8px;
                border: 1px solid #dbdbdb;
                border-radius: 4px;
                background-color: white;
                min-width: 250px;
            }
            QPushButton {
                background-color: #0095f6;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
        """)

        # Username input
        username_label = QLabel('Kullanıcı Adı:')
        layout.addWidget(username_label)
        self.username_input = QLineEdit()
        layout.addWidget(self.username_input)

        # Password input
        password_label = QLabel('Şifre:')
        layout.addWidget(password_label)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password_input)

        # Login button
        self.login_button = QPushButton('Giriş Yap')
        self.login_button.clicked.connect(self.accept)
        layout.addWidget(self.login_button)

        self.setLayout(layout)

class InstagramDownloader(QThread):
    progress_updated = pyqtSignal(int)
    status_updated = pyqtSignal(str)
    
    def __init__(self, hashtag, video_count=10):
        super().__init__()
        self.hashtag = hashtag
        self.video_count = video_count
        self.is_running = True
        self.L = None
        self.initialize_loader()

    def initialize_loader(self):
        self.L = instaloader.Instaloader(
            download_videos=True,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            filename_pattern='{date_utc:%Y%m%d_%H%M%S}_{shortcode}'
        )

    def login(self, username, password):
        try:
            self.status_updated.emit("Giriş yapılıyor...")
            session_file = f"{username}_session"

            # Önce mevcut oturumu yüklemeyi dene
            try:
                self.L.load_session_from_file(username, session_file)
                # Oturumu test et
                test_profile = instaloader.Profile.from_username(self.L.context, username)
                self.status_updated.emit("Mevcut oturum yüklendi!")
                return True
            except (FileNotFoundError, LoginRequiredException):
                # Yeni oturum oluştur
                try:
                    self.L.login(username, password)
                    self.L.save_session_to_file(session_file)
                    self.status_updated.emit("Yeni oturum oluşturuldu!")
                    return True
                except BadCredentialsException:
                    self.status_updated.emit("Hatalı kullanıcı adı veya şifre!")
                    return False

        except Exception as e:
            self.status_updated.emit(f"Giriş hatası: {str(e)}")
            return False

    def run(self):
        try:
            self.status_updated.emit("Hashtag araması başlatılıyor...")
            posts = []
            
            try:
                hashtag_obj = instaloader.Hashtag.from_name(self.L.context, self.hashtag)
                self.status_updated.emit(f"#{self.hashtag} için içerikler alınıyor...")
                
                for post in hashtag_obj.get_posts():
                    if not self.is_running:
                        break
                        
                    if post.is_video and len(posts) < self.video_count:
                        posts.append(post)
                        self.status_updated.emit(f"Video bulundu: {len(posts)}/{self.video_count}")
                    
                    if len(posts) >= self.video_count:
                        break
                        
                    time.sleep(1)  # Rate limiting
                    
            except LoginRequiredException:
                self.status_updated.emit("Giriş yapılması gerekiyor!")
                return
            except Exception as e:
                self.status_updated.emit(f"Hashtag arama hatası: {str(e)}")
                return

            if not posts:
                self.status_updated.emit("Video bulunamadı.")
                return

            # İndirme klasörünü oluştur
            download_path = os.path.join(os.getcwd(), 'downloads')
            if not os.path.exists(download_path):
                os.makedirs(download_path)

            # Videoları indir
            for index, post in enumerate(posts):
                if not self.is_running:
                    break

                try:
                    self.status_updated.emit(f"Video indiriliyor: {index + 1}/{len(posts)}")
                    self.L.download_post(post, target=download_path)
                    
                    progress = int((index + 1) / len(posts) * 100)
                    self.progress_updated.emit(progress)
                    
                    if index < len(posts) - 1:
                        time.sleep(2)  # Rate limiting

                except Exception as e:
                    self.status_updated.emit(f"İndirme hatası: {str(e)}")
                    continue

            if self.is_running:
                self.status_updated.emit("İndirme tamamlandı!")
                self.status_updated.emit(f"Videolar '{download_path}' klasörüne kaydedildi.")
            else:
                self.status_updated.emit("İndirme durduruldu.")

        except Exception as e:
            self.status_updated.emit(f"Genel hata: {str(e)}")

    def stop(self):
        self.is_running = False

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.downloader = None

    def initUI(self):
        self.setWindowTitle('Instagram Video İndirici')
        self.setGeometry(100, 100, 800, 600)
        self.setStyleSheet("""
            QMainWindow {
                background-color: #fafafa;
            }
            QLabel {
                color: #262626;
                font-size: 14px;
            }
            QPushButton {
                background-color: #0095f6;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
                min-width: 100px;
            }
            QPushButton:disabled {
                background-color: #B2DFFC;
            }
            QLineEdit {
                padding: 8px;
                border: 1px solid #dbdbdb;
                border-radius: 4px;
                background-color: white;
            }
            QTextEdit {
                border: 1px solid #dbdbdb;
                border-radius: 4px;
                background-color: white;
            }
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout()

        # Header
        header_label = QLabel('Instagram Video İndirici')
        header_label.setAlignment(Qt.AlignCenter)
        header_label.setStyleSheet('font-size: 24px; font-weight: bold; margin: 20px;')
        layout.addWidget(header_label)

        # Input fields
        input_layout = QHBoxLayout()
        
        input_group = QVBoxLayout()
        hashtag_label = QLabel('Hashtag:')
        self.hashtag_input = QLineEdit()
        self.hashtag_input.setPlaceholderText('Hashtag giriniz (# olmadan)')
        input_group.addWidget(hashtag_label)
        input_group.addWidget(self.hashtag_input)
        
        count_group = QVBoxLayout()
        count_label = QLabel('Video Sayısı:')
        self.count_input = QLineEdit()
        self.count_input.setPlaceholderText('10')
        self.count_input.setText('10')
        self.count_input.setMaximumWidth(100)
        count_group.addWidget(count_label)
        count_group.addWidget(self.count_input)
        
        input_layout.addLayout(input_group)
        input_layout.addLayout(count_group)
        layout.addLayout(input_layout)

        # Buttons
        button_layout = QHBoxLayout()
        
        self.login_button = QPushButton('Giriş Yap')
        self.login_button.clicked.connect(self.show_login_dialog)
        button_layout.addWidget(self.login_button)
        
        self.download_button = QPushButton('İndir')
        self.download_button.clicked.connect(self.start_download)
        self.download_button.setEnabled(False)
        button_layout.addWidget(self.download_button)
        
        self.stop_button = QPushButton('Durdur')
        self.stop_button.clicked.connect(self.stop_download)
        self.stop_button.setEnabled(False)
        button_layout.addWidget(self.stop_button)
        
        layout.addLayout(button_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #dbdbdb;
                border-radius: 4px;
                text-align: center;
                height: 25px;
            }
            QProgressBar::chunk {
                background-color: #0095f6;
            }
        """)
        layout.addWidget(self.progress_bar)

        # Status text
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMinimumHeight(300)
        layout.addWidget(self.status_text)

        central_widget.setLayout(layout)

    def show_login_dialog(self):
        dialog = LoginDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            username = dialog.username_input.text().strip()
            password = dialog.password_input.text().strip()
            
            if not username or not password:
                QMessageBox.warning(self, "Hata", "Kullanıcı adı ve şifre gerekli!")
                return

            self.downloader = InstagramDownloader("temp", 1)
            if self.downloader.login(username, password):
                self.login_button.setText("Giriş Yapıldı")
                self.login_button.setEnabled(False)
                self.download_button.setEnabled(True)
                self.update_status("Giriş başarılı! İndirme işlemi için hazır.")
            else:
                QMessageBox.warning(self, "Hata", "Giriş başarısız! Lütfen bilgilerinizi kontrol edin.")

    def start_download(self):
        hashtag = self.hashtag_input.text().strip()
        try:
            video_count = int(self.count_input.text())
            if video_count <= 0:
                raise ValueError()
        except ValueError:
            QMessageBox.warning(self, "Hata", "Geçerli bir video sayısı giriniz!")
            return

        if not hashtag:
            QMessageBox.warning(self, "Hata", "Lütfen bir hashtag giriniz!")
            return

        self.downloader = InstagramDownloader(hashtag, video_count)
        if not self.downloader.login(self.downloader.L.context.username, None):
            QMessageBox.warning(self, "Hata", "Oturum hatası! Lütfen tekrar giriş yapın.")
            self.login_button.setEnabled(True)
            self.download_button.setEnabled(False)
            return

        self.download_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.status_text.clear()

        self.downloader.progress_updated.connect(self.update_progress)
        self.downloader.status_updated.connect(self.update_status)
        self.downloader.finished.connect(self.download_finished)
        self.downloader.start()

    def stop_download(self):
        if self.downloader:
            self.downloader.stop()
            self.update_status("İndirme durduruldu.")
            self.download_finished()

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_status(self, message):
        self.status_text.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
        self.status_text.verticalScrollBar().setValue(
            self.status_text.verticalScrollBar().maximum()
        )

    def download_finished(self):
        self.download_button.setEnabled(True)
        self.stop_button.setEnabled(False)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    ex = MainWindow()
    ex.show()
    sys.exit(app.exec_())