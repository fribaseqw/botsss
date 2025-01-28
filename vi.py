import sys
import os
import hashlib
import json
import time
import logging
import sqlite3
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                          QHBoxLayout, QLineEdit, QPushButton, QLabel, 
                          QProgressBar, QTextEdit, QFileDialog, QMessageBox,
                          QCheckBox, QComboBox, QTabWidget)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from instagrapi import Client
import requests
from tiktokapipy.api import TikTokAPI  # DEĞİŞTİ
import re
# Logging ayarları
logging.basicConfig(
    filename='social_media_downloader.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class SQLiteMediaTracker:
    def __init__(self, db_path="downloads.db"):
        self.db_path = db_path
        self.init_database()
        
    def init_database(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS downloaded_media (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        media_id TEXT NOT NULL,
                        media_hash TEXT UNIQUE NOT NULL,
                        media_url TEXT NOT NULL,
                        file_path TEXT NOT NULL,
                        media_type TEXT NOT NULL,
                        platform TEXT NOT NULL,
                        hashtag TEXT,
                        downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_media_hash ON downloaded_media(media_hash)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_media_id ON downloaded_media(media_id)')
                conn.commit()
        except Exception as e:
            logging.error(f"Veritabanı başlatma hatası: {e}")

    def is_media_downloaded(self, media_id, media_url):
        try:
            media_url_str = str(media_url)
            media_hash = hashlib.md5(media_url_str.encode('utf-8')).hexdigest()
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM downloaded_media WHERE media_hash = ? OR media_id = ?',
                             (media_hash, media_id))
                return cursor.fetchone()[0] > 0
        except Exception as e:
            logging.error(f"Medya kontrol hatası: {e}")
            return False

    def add_media(self, media_id, media_url, file_path, media_type, platform, hashtag=None):
        try:
            media_url_str = str(media_url)
            media_hash = hashlib.md5(media_url_str.encode('utf-8')).hexdigest()
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO downloaded_media 
                    (media_id, media_hash, media_url, file_path, media_type, platform, hashtag)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (media_id, media_hash, media_url_str, file_path, media_type, platform, hashtag))
                conn.commit()
            return True
        except sqlite3.IntegrityError:
            logging.warning(f"Medya zaten var: {media_id}")
            return False
        except Exception as e:
            logging.error(f"Medya ekleme hatası: {e}")
            return False

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
        self.media_tracker = SQLiteMediaTracker()

    def download_media(self, url, filename, media_id, media_type):
        try:
            if self.media_tracker.is_media_downloaded(media_id, url):
                self.progress_updated.emit(f"Medya zaten indirilmiş: {os.path.basename(filename)}")
                return False

            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()

            with open(filename, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if not self.is_running:
                        f.close()
                        os.remove(filename)
                        return False
                    if chunk:
                        f.write(chunk)

            if self.media_tracker.add_media(
                media_id=media_id,
                media_url=url,
                file_path=filename,
                media_type=media_type,
                platform='instagram',
                hashtag=self.hashtag
            ):
                return True
            return False

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

                    if media.media_type == 1 and self.download_photos:
                        url = str(media.thumbnail_url)
                        ext = '.jpg'
                        media_type = 'photo'
                    elif media.media_type == 2 and self.download_videos:
                        url = str(media.video_url)
                        ext = '.mp4'
                        media_type = 'video'
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

                    if self.download_media(url, filename, media_id, media_type):
                        downloaded_count += 1
                        self.progress_count.emit(int((downloaded_count / total_count) * 100))
                        self.progress_updated.emit(
                            f"İndirilen medya {downloaded_count}/{total_count}: "
                            f"{os.path.basename(filename)}"
                        )
                    else:
                        skipped_count += 1

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

# TikTokDownloaderThread sınıfını güncelliyoruz
# Önce gerekli kütüphaneyi yükleyelim
# pip install tiktok-dl

class TikTokDownloaderThread(QThread):
    progress_updated = pyqtSignal(str)
    download_complete = pyqtSignal(str)
    download_error = pyqtSignal(str)
    progress_count = pyqtSignal(int)

    def __init__(self, keyword, download_path, limit=None):
        super().__init__()
        self.keyword = keyword
        self.download_path = download_path
        self.limit = limit
        self.is_running = True
        self.media_tracker = SQLiteMediaTracker()

    def get_video_info(self, keyword):
        try:
            # Hashtag veya arama kelimesi kontrolü
            if keyword.startswith('#'):
                encoded_keyword = keyword[1:]  # # işaretini kaldır
                url = f"https://www.tiktok.com/tag/{encoded_keyword}"
            else:
                encoded_keyword = keyword
                url = f"https://www.tiktok.com/search?q={encoded_keyword}"

            headers = {
                'authority': 'www.tiktok.com',
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'accept-language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
                'cache-control': 'no-cache',
                'pragma': 'no-cache',
                'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'document',
                'sec-fetch-mode': 'navigate',
                'sec-fetch-site': 'none',
                'sec-fetch-user': '?1',
                'upgrade-insecure-requests': '1',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }

            response = requests.get(url, headers=headers)

            if response.status_code != 200:
                self.download_error.emit(f"Sayfa yüklenemedi: HTTP {response.status_code}")
                return []

            # Daha kapsamlı regex pattern'ler
            patterns = [
                # Pattern 1: Standart video data
                r'"videoData":\s*({[^}]+})',
                # Pattern 2: Video URL pattern
                r'"playAddr":"([^"]+)".*?"id":"(\d+)".*?"desc":"([^"]+)"',
                # Pattern 3: Alternatif video data
                r'<script id="SIGI_STATE" type="application/json">(.*?)</script>',
                # Pattern 4: Video detayları
                r'"video":{"id":"([^"]+)","desc":"([^"]+)","playAddr":"([^"]+)"'
            ]

            videos = []
            html_content = response.text

            for pattern in patterns:
                matches = re.finditer(pattern, html_content)
                for match in matches:
                    try:
                        if len(match.groups()) == 1 and '{' in match.group(1):
                            # JSON verisi içeren pattern
                            data = json.loads(match.group(1))
                            if 'playAddr' in str(data):
                                video_url = data.get('playAddr', '')
                                video_id = data.get('id', '')
                                desc = data.get('desc', '')
                        else:
                            # URL pattern
                            if len(match.groups()) == 3:
                                if pattern == patterns[1]:  # Pattern 2
                                    video_url, video_id, desc = match.groups()
                                else:  # Pattern 4
                                    video_id, desc, video_url = match.groups()
                            else:
                                continue

                        # URL'yi temizle
                        video_url = video_url.replace('\\u002F', '/').replace('\\\\u002F', '/').replace('&amp;', '&')

                        # Tam URL kontrolü
                        if not video_url.startswith('http'):
                            video_url = f"https://www.tiktok.com{video_url}"

                        if video_url and video_id:
                            video_info = {
                                'id': video_id,
                                'desc': desc,
                                'url': video_url
                            }
                            if video_info not in videos:  # Tekrarları önle
                                videos.append(video_info)

                    except Exception as e:
                        continue

            # Debug bilgisi
            if not videos:
                self.download_error.emit("Video bulunamadı! HTML içeriği kontrol ediliyor...")
                # HTML içeriğini kaydet (debug için)
                with open('tiktok_debug.html', 'w', encoding='utf-8') as f:
                    f.write(html_content)

            return videos[:self.limit] if self.limit and videos else videos

        except Exception as e:
            self.download_error.emit(f"Video bilgisi alma hatası: {str(e)}")
            return []
    def download_video(self, video_info):
        try:
            video_id = video_info['id']
            video_url = video_info['url']
            desc = video_info['desc']
    
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            safe_desc = "".join(x for x in desc if x.isalnum() or x in (' ', '-', '_'))[:30]
            filename = os.path.join(
                self.download_path,
                f"tiktok_{timestamp}_{safe_desc}.mp4"
            )
    
            if self.media_tracker.is_media_downloaded(video_id, video_url):
                self.progress_updated.emit(f"Video zaten indirilmiş: {os.path.basename(filename)}")
                return False
    
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Referer': 'https://www.tiktok.com/',
                'Range': 'bytes=0-',
                'Accept': '*/*',
                'Origin': 'https://www.tiktok.com',
                'Sec-Fetch-Site': 'cross-site',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Dest': 'video'
            }
    
            with requests.get(video_url, headers=headers, stream=True) as response:
                response.raise_for_status()
                
                with open(filename, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if not self.is_running:
                            f.close()
                            os.remove(filename)
                            return False
                        if chunk:
                            f.write(chunk)
    
            self.media_tracker.add_media(
                media_id=video_id,
                media_url=video_url,
                file_path=filename,
                media_type='video',
                platform='tiktok',
                hashtag=self.keyword
            )
    
            return True
    
        except Exception as e:
            self.download_error.emit(f"Video indirme hatası: {str(e)}")
            if 'filename' in locals():
                try:
                    os.remove(filename)
                except:
                    pass
            return False
    def run(self):
        try:
            self.progress_updated.emit("TikTok bağlantısı başlatılıyor...")
            videos = self.get_video_info(self.keyword)

            if not videos:
                self.download_error.emit("Video bulunamadı!")
                return

            total_count = len(videos)
            self.progress_updated.emit(f"Toplam {total_count} video bulundu")

            downloaded_count = 0
            skipped_count = 0

            for index, video in enumerate(videos):
                if not self.is_running:
                    break

                try:
                    if self.download_video(video):
                        downloaded_count += 1
                        self.progress_count.emit(int((downloaded_count / total_count) * 100))
                        self.progress_updated.emit(
                            f"İndirilen video {downloaded_count}/{total_count}: "
                            f"{video['desc'][:50]}..."
                        )
                    else:
                        skipped_count += 1

                except Exception as e:
                    self.download_error.emit(f"Video işleme hatası: {str(e)}")
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

    def stop(self):
        self.is_running = False
class SocialMediaDownloaderGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.downloader_thread = None
        self.last_download_path = ""
        self.load_last_path()

    def initUI(self):
        self.setWindowTitle('Sosyal Medya İndirici')
        self.setGeometry(100, 100, 800, 600)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Platform seçimi
        platform_layout = QHBoxLayout()
        self.platform_combo = QComboBox()
        self.platform_combo.addItems(['Instagram', 'TikTok'])
        self.platform_combo.currentTextChanged.connect(self.on_platform_change)
        platform_layout.addWidget(QLabel('Platform:'))
        platform_layout.addWidget(self.platform_combo)
        layout.addLayout(platform_layout)

        # Tab widget
        self.tab_widget = QTabWidget()
        self.instagram_tab = QWidget()
        self.tiktok_tab = QWidget()
        self.setup_instagram_tab()
        self.setup_tiktok_tab()
        self.tab_widget.addTab(self.instagram_tab, "Instagram")
        self.tab_widget.addTab(self.tiktok_tab, "TikTok")
        layout.addWidget(self.tab_widget)

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

    def on_platform_change(self, platform):
        """
        Platform değiştiğinde sekmeler arasında geçiş yapar
        """
        if platform == 'Instagram':
            self.tab_widget.setCurrentWidget(self.instagram_tab)
            self.tiktok_keyword_input.clear()
            self.tiktok_limit_input.clear()
        else:  # TikTok
            self.tab_widget.setCurrentWidget(self.tiktok_tab)
            self.instagram_username_input.clear()
            self.instagram_password_input.clear()
            self.instagram_hashtag_input.clear()
            self.instagram_limit_input.clear()

        # Platform değiştiğinde indirme butonunu aktif et
        self.download_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.log_text.clear()
        self.statusBar().showMessage('Hazır')



    def setup_instagram_tab(self):
        layout = QVBoxLayout(self.instagram_tab)

        # Instagram kullanıcı girişi
        login_group = QVBoxLayout()
        
        username_layout = QHBoxLayout()
        self.instagram_username_input = QLineEdit()
        self.instagram_username_input.setPlaceholderText('Instagram kullanıcı adı')
        username_layout.addWidget(QLabel('Kullanıcı Adı:'))
        username_layout.addWidget(self.instagram_username_input)
        login_group.addLayout(username_layout)

        password_layout = QHBoxLayout()
        self.instagram_password_input = QLineEdit()
        self.instagram_password_input.setPlaceholderText('Instagram şifresi')
        self.instagram_password_input.setEchoMode(QLineEdit.Password)
        password_layout.addWidget(QLabel('Şifre:'))
        password_layout.addWidget(self.instagram_password_input)
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
        self.instagram_hashtag_input = QLineEdit()
        self.instagram_hashtag_input.setPlaceholderText('Hashtag girin (# olmadan)')
        hashtag_layout.addWidget(QLabel('Hashtag:'))
        hashtag_layout.addWidget(self.instagram_hashtag_input)
        layout.addLayout(hashtag_layout)

        # Limit girişi
        limit_layout = QHBoxLayout()
        self.instagram_limit_input = QLineEdit()
        self.instagram_limit_input.setPlaceholderText('Boş bırakın veya sayı girin')
        limit_layout.addWidget(QLabel('Medya Limiti:'))
        limit_layout.addWidget(self.instagram_limit_input)
        layout.addLayout(limit_layout)

        layout.addStretch()

    def setup_tiktok_tab(self):
        layout = QVBoxLayout(self.tiktok_tab)

        # Ana grup
        main_group = QVBoxLayout()

        # Arama kelimesi girişi
        search_group = QHBoxLayout()
        self.tiktok_keyword_input = QLineEdit()
        self.tiktok_keyword_input.setPlaceholderText('Arama kelimesi veya hashtag girin')
        search_group.addWidget(QLabel('Arama:'))
        search_group.addWidget(self.tiktok_keyword_input)
        main_group.addLayout(search_group)

        # Limit girişi
        limit_group = QHBoxLayout()
        self.tiktok_limit_input = QLineEdit()
        self.tiktok_limit_input.setPlaceholderText('Boş bırakın veya sayı girin')
        limit_group.addWidget(QLabel('Video Limiti:'))
        limit_group.addWidget(self.tiktok_limit_input)
        main_group.addLayout(limit_group)

        # İndirme seçenekleri grubu
        options_group = QVBoxLayout()

        # Video kalitesi seçimi
        quality_layout = QHBoxLayout()
        self.tiktok_quality_combo = QComboBox()
        self.tiktok_quality_combo.addItems(['En Yüksek Kalite', 'Normal Kalite'])
        quality_layout.addWidget(QLabel('Video Kalitesi:'))
        quality_layout.addWidget(self.tiktok_quality_combo)
        options_group.addLayout(quality_layout)

        # Watermark seçimi
        self.tiktok_watermark_check = QCheckBox('Watermark\'ı Kaldır (Mümkünse)')
        options_group.addWidget(self.tiktok_watermark_check)

        main_group.addLayout(options_group)

        # Bilgi etiketleri
        info_group = QVBoxLayout()
        info_label1 = QLabel("Not: TikTok aramalarında hashtag için '#' kullanabilirsiniz.")
        info_label2 = QLabel("Örnek: #trending veya dans")
        info_label1.setStyleSheet("color: gray;")
        info_label2.setStyleSheet("color: gray;")
        info_group.addWidget(info_label1)
        info_group.addWidget(info_label2)
        main_group.addLayout(info_group)

        # Ana düzene ekle
        layout.addLayout(main_group)
        layout.addStretch()


    def validate_tiktok_inputs(self):
       """TikTok indirme işlemi için girişleri doğrular"""
       if not self.path_input.text().strip():
           QMessageBox.warning(self, 'Hata', 'İndirme klasörü seçilmelidir.')
           return False

       if not self.tiktok_keyword_input.text().strip():
           QMessageBox.warning(self, 'Hata', 'Arama kelimesi veya hashtag gereklidir.')
           return False

       limit_text = self.tiktok_limit_input.text().strip()
       if limit_text:
           try:
               limit = int(limit_text)
               if limit <= 0:
                   raise ValueError()
           except ValueError:
               QMessageBox.warning(self, 'Hata', 'Video limiti pozitif bir sayı olmalıdır.')
               return False

       return True    

    def prepare_tiktok_download(self):
        """TikTok indirme işlemini hazırlar ve başlatır"""
        if not self.validate_tiktok_inputs():
            return

        keyword = self.tiktok_keyword_input.text().strip()
        limit_text = self.tiktok_limit_input.text().strip()
        limit = int(limit_text) if limit_text else None
        download_path = self.path_input.text().strip()

        # Seçenekleri al
        is_high_quality = self.tiktok_quality_combo.currentText() == 'En Yüksek Kalite'
        remove_watermark = self.tiktok_watermark_check.isChecked()

        self.download_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log_text.clear()

        self.log_message("TikTok indirmesi başlatılıyor...")

        # Downloader thread'i oluştur ve başlat
        self.downloader_thread = TikTokDownloaderThread(
            keyword=keyword,
            download_path=download_path,
            limit=limit
        )

        # Sinyalleri bağla
        self.downloader_thread.progress_updated.connect(self.log_message)
        self.downloader_thread.download_complete.connect(self.download_finished)
        self.downloader_thread.download_error.connect(self.log_message)
        self.downloader_thread.progress_count.connect(self.progress_bar.setValue)

        # Thread'i başlat
        self.downloader_thread.start()

    def update_tiktok_ui_state(self, is_downloading):
        """TikTok sekmesindeki UI elemanlarının durumunu günceller"""
        self.tiktok_keyword_input.setEnabled(not is_downloading)
        self.tiktok_limit_input.setEnabled(not is_downloading)
        self.tiktok_quality_combo.setEnabled(not is_downloading)
        self.tiktok_watermark_check.setEnabled(not is_downloading)
        self.download_button.setEnabled(not is_downloading)
        self.stop_button.setEnabled(is_downloading)
        def on_platform_change(self, platform):
            self.tab_widget.setCurrentIndex(0 if platform == 'Instagram' else 1)

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
        if not self.path_input.text().strip():
            QMessageBox.warning(self, 'Hata', 'İndirme klasörü seçilmelidir.')
            return False

        current_platform = self.platform_combo.currentText()
        
        if current_platform == 'Instagram':
            if not self.instagram_username_input.text().strip():
                QMessageBox.warning(self, 'Hata', 'Instagram kullanıcı adı gereklidir.')
                return False
                
            if not self.instagram_password_input.text().strip():
                QMessageBox.warning(self, 'Hata', 'Instagram şifresi gereklidir.')
                return False

            if not self.instagram_hashtag_input.text().strip():
                QMessageBox.warning(self, 'Hata', 'Instagram hashtag gereklidir.')
                return False
                
            if not self.photo_checkbox.isChecked() and not self.video_checkbox.isChecked():
                QMessageBox.warning(self, 'Hata', 'En az bir medya türü seçilmelidir.')
                return False
        
        elif current_platform == 'TikTok':
            if not self.tiktok_keyword_input.text().strip():
                QMessageBox.warning(self, 'Hata', 'TikTok arama kelimesi gereklidir.')
                return False

        return True

    def start_download(self):
        if not self.validate_inputs():
            return

        current_platform = self.platform_combo.currentText()
        download_path = self.path_input.text().strip()

        self.download_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log_text.clear()

        if current_platform == 'Instagram':
            hashtag = self.instagram_hashtag_input.text().strip()
            limit_text = self.instagram_limit_input.text().strip()
            username = self.instagram_username_input.text().strip()
            password = self.instagram_password_input.text().strip()

            try:
                limit = int(limit_text) if limit_text else None
                if limit is not None and limit <= 0:
                    raise ValueError("Limit pozitif olmalıdır")
            except ValueError as e:
                QMessageBox.warning(self, 'Hata', f'Geçersiz limit: {str(e)}')
                self.download_button.setEnabled(True)
                self.stop_button.setEnabled(False)
                return

            self.log_message("Instagram indirmesi başlatılıyor...")
            
            self.downloader_thread = InstagramDownloaderThread(
                hashtag=hashtag,
                download_path=download_path,
                limit=limit,
                username=username,
                password=password,
                download_photos=self.photo_checkbox.isChecked(),
                download_videos=self.video_checkbox.isChecked()
            )

        else:  # TikTok
            keyword = self.tiktok_keyword_input.text().strip()
            limit_text = self.tiktok_limit_input.text().strip()

            try:
                limit = int(limit_text) if limit_text else None
                if limit is not None and limit <= 0:
                    raise ValueError("Limit pozitif olmalıdır")
            except ValueError as e:
                QMessageBox.warning(self, 'Hata', f'Geçersiz limit: {str(e)}')
                self.download_button.setEnabled(True)
                self.stop_button.setEnabled(False)
                return

            self.log_message("TikTok indirmesi başlatılıyor...")
            
            self.downloader_thread = TikTokDownloaderThread(
                keyword=keyword,
                download_path=download_path,
                limit=limit
            )

        self.downloader_thread.progress_updated.connect(self.log_message)
        self.downloader_thread.download_complete.connect(self.download_finished)
        self.downloader_thread.download_error.connect(self.log_message)
        self.downloader_thread.progress_count.connect(self.progress_bar.setValue)
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
    ex = SocialMediaDownloaderGUI()
    ex.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()