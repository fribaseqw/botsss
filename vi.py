import sys
import os
import requests
import json
import time
import random
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLineEdit, QPushButton, QLabel, 
                            QProgressBar, QTextEdit, QMessageBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QIcon, QFont
import uuid

class InstagramDownloader(QThread):
    progress_updated = pyqtSignal(int)
    status_updated = pyqtSignal(str)
    
    def __init__(self, hashtag, video_count=10):
        super().__init__()
        self.hashtag = hashtag
        self.video_count = video_count
        self.is_running = True
        self.session = requests.Session()
        self.device_id = self.generate_device_id()
        self.api_domain = 'i.instagram.com'
        
    def generate_device_id(self):
        return str(uuid.uuid4())

    def get_headers(self):
        return {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_8 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 123.0.0.21.115 (iPhone11,8; iOS 14_8; en_US; en-US; scale=2.00; 828x1792; 190542906)',
            'Accept': '*/*',
            'Accept-Language': 'en-US',
            'Accept-Encoding': 'gzip, deflate',
            'X-IG-Capabilities': '3brTvx8=',
            'X-IG-Connection-Type': 'WIFI',
            'X-IG-App-ID': '567067343352427',
            'X-IG-Device-ID': self.device_id,
            'X-IG-Android-ID': self.device_id,
            'Origin': 'https://www.instagram.com',
            'Connection': 'keep-alive',
            'Referer': 'https://www.instagram.com/',
        }

    def get_hashtag_feed(self):
        try:
            url = f'https://{self.api_domain}/api/v1/feed/tag/{self.hashtag}/'
            
            params = {
                'count': 50,
                'max_id': '',
                'rank_token': str(uuid.uuid4()),
                'seen_posts': '[]'
            }
            
            response = self.session.get(url, headers=self.get_headers(), params=params)
            
            if response.status_code == 200:
                return response.json()
            else:
                self.status_updated.emit(f"API yanıt kodu: {response.status_code}")
                return None

        except Exception as e:
            self.status_updated.emit(f"Veri çekme hatası: {str(e)}")
            return None

    def download_video(self, video_url, file_path):
        try:
            headers = self.get_headers()
            headers['Accept'] = 'video/mp4'
            
            response = self.session.get(video_url, headers=headers, stream=True)
            if response.status_code == 200:
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=1024*1024):
                        if not self.is_running:
                            return False
                        if chunk:
                            f.write(chunk)
                return True
            return False
        except Exception as e:
            self.status_updated.emit(f"İndirme hatası: {str(e)}")
            return False

    def run(self):
        try:
            self.status_updated.emit("Hashtag içerikleri aranıyor...")
            videos_found = []
            retry_count = 0
            max_retries = 3

            while len(videos_found) < self.video_count and retry_count < max_retries and self.is_running:
                data = self.get_hashtag_feed()
                
                if not data:
                    retry_count += 1
                    self.status_updated.emit(f"Yeniden deneniyor... ({retry_count}/{max_retries})")
                    time.sleep(2)
                    continue

                try:
                    items = data.get('items', [])
                    
                    for item in items:
                        if not self.is_running:
                            break
                            
                        if item.get('media_type') == 2:  # Video type
                            if 'video_versions' in item:
                                video_url = item['video_versions'][0]['url']
                                if len(videos_found) < self.video_count:
                                    videos_found.append({
                                        'url': video_url,
                                        'id': item.get('id', '')
                                    })
                                    self.status_updated.emit(f"Video bulundu: {len(videos_found)}/{self.video_count}")
                        
                        if len(videos_found) >= self.video_count:
                            break

                except Exception as e:
                    self.status_updated.emit(f"Veri işleme hatası: {str(e)}")
                    continue

            # İndirme işlemi
            if videos_found:
                if not os.path.exists('downloads'):
                    os.makedirs('downloads')

                for index, video in enumerate(videos_found):
                    if not self.is_running:
                        break

                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    file_name = f'downloads/{self.hashtag}_{timestamp}_{index + 1}.mp4'
                    
                    self.status_updated.emit(f"Video indiriliyor: {index + 1}/{len(videos_found)}")
                    if self.download_video(video['url'], file_name):
                        progress = int((index + 1) / len(videos_found) * 100)
                        self.progress_updated.emit(progress)
                    else:
                        self.status_updated.emit(f"Video indirilemedi: {index + 1}")

                    time.sleep(1.5)  # Rate limiting

                if self.is_running:
                    self.status_updated.emit("Tüm videolar indirildi!")
                else:
                    self.status_updated.emit("İndirme işlemi durduruldu.")
            else:
                self.status_updated.emit("Hiç video bulunamadı.")

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
        self.setWindowTitle('Instagram Hashtag Video İndirici')
        self.setGeometry(100, 100, 600, 400)
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
        header_label = QLabel('Instagram Hashtag Video İndirici')
        header_label.setAlignment(Qt.AlignCenter)
        header_label.setStyleSheet('font-size: 18px; font-weight: bold; margin: 10px;')
        layout.addWidget(header_label)

        # Input fields
        input_layout = QHBoxLayout()
        
        self.hashtag_input = QLineEdit()
        self.hashtag_input.setPlaceholderText('Hashtag giriniz (# olmadan)')
        input_layout.addWidget(self.hashtag_input)
        
        self.count_input = QLineEdit()
        self.count_input.setPlaceholderText('Video sayısı')
        self.count_input.setText('10')
        self.count_input.setMaximumWidth(100)
        input_layout.addWidget(self.count_input)
        
        layout.addLayout(input_layout)

        # Buttons
        button_layout = QHBoxLayout()
        
        self.download_button = QPushButton('İndir')
        self.download_button.clicked.connect(self.start_download)
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
            }
            QProgressBar::chunk {
                background-color: #0095f6;
            }
        """)
        layout.addWidget(self.progress_bar)

        # Status text
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMinimumHeight(200)
        layout.addWidget(self.status_text)

        central_widget.setLayout(layout)

    def start_download(self):
        hashtag = self.hashtag_input.text().strip()
        try:
            video_count = int(self.count_input.text())
            if video_count <= 0:
                raise ValueError("Video sayısı pozitif olmalıdır.")
        except ValueError as e:
            QMessageBox.warning(self, "Hata", "Geçerli bir video sayısı giriniz!")
            return

        if not hashtag:
            QMessageBox.warning(self, "Hata", "Lütfen bir hashtag giriniz!")
            return

        self.download_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.status_text.clear()

        self.downloader = InstagramDownloader(hashtag, video_count)
        self.downloader.progress_updated.connect(self.update_progress)
        self.downloader.status_updated.connect(self.update_status)
        self.downloader.finished.connect(self.download_finished)
        self.downloader.start()

    def stop_download(self):
        if self.downloader:
            self.downloader.stop()
            self.status_text.append("İndirme durduruldu.")
            self.download_finished()

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_status(self, message):
        self.status_text.append(message)
        self.status_text.verticalScrollBar().setValue(
            self.status_text.verticalScrollBar().maximum()
        )

    def download_finished(self):
        self.download_button.setEnabled(True)
        self.stop_button.setEnabled(False)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = MainWindow()
    ex.show()
    sys.exit(app.exec_())