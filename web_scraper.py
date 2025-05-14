import logging
import aiohttp
import asyncio
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import time
import os
import json
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("web_scraper.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class WebScraper:
    def __init__(self, db=None):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
        }
        self.timeout = 10  # Таймаут запроса в секундах
        self.retry_count = 3  # Количество попыток при неудаче
        self.retry_delay = 2  # Задержка между попытками в секундах
        self.db = db  # Ссылка на объект базы данных
        self.cache_file = "url_cache.json"  # Файл для кэширования обработанных URL
        self.cache_expiry = 30  # Срок хранения URL в кэше (в днях)
        self.url_cache = self._load_cache()  # Загрузка кэша URL
        self.session = None  # Сессия aiohttp будет создана при первом использовании
        
        # Расширенный список IT-тематик для фильтрации
        self.it_keywords = [
            "AI", "artificial intelligence", "machine learning", "deep learning", "neural network",
            "Web3", "blockchain", "cryptocurrency", "NFT", "smart contract", "DeFi", "DAO",
            "cybersecurity", "security", "hacking", "malware", "ransomware", "phishing", "encryption",
            "UX", "UI", "user experience", "user interface", "design", "frontend", "mobile app",
            "programming", "coding", "software development", "developer", "engineer", "DevOps",
            "cloud", "AWS", "Azure", "Google Cloud", "serverless", "microservices", "containers",
            "data science", "big data", "analytics", "database", "SQL", "NoSQL", "data mining",
            "API", "REST", "GraphQL", "web service", "integration", "backend", "fullstack",
            "IoT", "Internet of Things", "embedded systems", "robotics", "automation",
            "VR", "AR", "virtual reality", "augmented reality", "metaverse", "gaming",
            "startup", "tech industry", "innovation", "digital transformation", "SaaS", "PaaS", "IaaS",
            "agile", "scrum", "kanban", "project management", "product management",
            "open source", "git", "github", "version control", "CI/CD", "testing", "QA",
            "Python", "JavaScript", "Java", "C++", "C#", "Go", "Rust", "TypeScript", "PHP", "Ruby",
            "React", "Angular", "Vue", "Node.js", "Django", "Flask", "Spring", "ASP.NET", "Laravel"
        ]
        
        # Добавление новых ключевых слов для более точной фильтрации
        self.it_keywords.extend([
            "algorithm", "data structure", "software architecture", "system design",
            "quantum computing", "edge computing", "5G", "network", "protocol",
            "fintech", "healthtech", "edtech", "proptech", "regtech", "insurtech",
            "computer vision", "NLP", "natural language processing", "speech recognition",
            "chatbot", "LLM", "large language model", "GPT", "transformer", "BERT",
            "kubernetes", "docker", "terraform", "ansible", "jenkins", "gitlab",
            "cybersecurity", "zero trust", "penetration testing", "vulnerability",
            "data privacy", "GDPR", "compliance", "encryption", "authentication",
            "low-code", "no-code", "citizen developer", "digital twin", "augmented analytics",
            "MLOps", "AIOps", "DataOps", "DevSecOps", "GitOps", "platform engineering"
        ])
    
    async def get_session(self):
        """Получение или создание aiohttp сессии"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers=self.headers)
        return self.session
    
    async def close(self):
        """Закрытие aiohttp сессии"""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("Сессия aiohttp закрыта")
    
    def _load_cache(self):
        """Загрузка кэша обработанных URL из файла"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                    # Очистка устаревших записей
                    now = datetime.now()
                    cleaned_cache = {}
                    for url, entry in cache.items():
                        # Поддержка как старого формата (строка), так и нового (словарь)
                        if isinstance(entry, str):
                            timestamp = entry
                            is_it_related = None  # Неизвестно для старых записей
                        else:
                            timestamp = entry.get('timestamp')
                            is_it_related = entry.get('is_it_related')
                        
                        cache_date = datetime.fromisoformat(timestamp)
                        if now - cache_date < timedelta(days=self.cache_expiry):
                            # Преобразование в новый формат
                            cleaned_cache[url] = {
                                'timestamp': timestamp,
                                'is_it_related': is_it_related
                            }
                    logger.info(f"Загружен кэш URL: {len(cleaned_cache)} записей (после очистки)")
                    return cleaned_cache
            return {}
        except Exception as e:
            logger.error(f"Ошибка при загрузке кэша URL: {e}")
            return {}
    
    def _save_cache(self):
        """Сохранение кэша обработанных URL в файл"""
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.url_cache, f, ensure_ascii=False, indent=2)
            logger.info(f"Кэш URL сохранен: {len(self.url_cache)} записей")
        except Exception as e:
            logger.error(f"Ошибка при сохранении кэша URL: {e}")
    
    def is_url_processed(self, url):
        """Проверка, был ли URL уже обработан"""
        # Проверка в кэше
        if url in self.url_cache:
            logger.debug(f"URL найден в кэше: {url}")
            return True
        
        # Проверка в базе данных, если она доступна
        if self.db:
            try:
                with self.db.conn.cursor() as cursor:
                    cursor.execute("SELECT id FROM news WHERE url = %s", (url,))
                    if cursor.fetchone() is not None:
                        # Добавляем URL в кэш
                        self.url_cache[url] = {
                            'timestamp': datetime.now().isoformat(),
                            'is_it_related': None  # Неизвестно, но уже в базе
                        }
                        self._save_cache()
                        logger.debug(f"URL найден в базе данных: {url}")
                        return True
            except Exception as e:
                logger.error(f"Ошибка при проверке URL в базе данных: {e}")
        
        return False
    
    def mark_url_processed(self, url, is_it_related=None):
        """Отметка URL как обработанного с информацией о релевантности"""
        self.url_cache[url] = {
            'timestamp': datetime.now().isoformat(),
            'is_it_related': is_it_related
        }
        self._save_cache()
    
    def is_it_related(self, title, content):
        """Проверка, относится ли статья к IT-тематике"""
        if not title and not content:
            return False
        
        # Преобразование в нижний регистр для поиска
        title_lower = title.lower() if title else ""
        content_lower = content.lower() if content else ""
        
        # Подсчет совпадений ключевых слов
        keyword_matches = 0
        matched_keywords = set()
        
        # Проверка заголовка (с большим весом)
        for keyword in self.it_keywords:
            keyword_lower = keyword.lower()
            # Проверка на точное совпадение слова (с границами слов)
            if re.search(r'\b' + re.escape(keyword_lower) + r'\b', title_lower):
                keyword_matches += 2  # Больший вес для совпадений в заголовке
                matched_keywords.add(keyword)
        
        # Проверка контента
        for keyword in self.it_keywords:
            keyword_lower = keyword.lower()
            # Проверка на точное совпадение слова (с границами слов)
            if re.search(r'\b' + re.escape(keyword_lower) + r'\b', content_lower):
                keyword_matches += 1
                matched_keywords.add(keyword)
        
        # Если найдено достаточное количество ключевых слов, считаем статью релевантной
        # Порог можно настроить в зависимости от требуемой точности
        is_related = keyword_matches >= 3 or len(matched_keywords) >= 2
        
        if is_related:
            logger.info(f"Статья соответствует IT-тематике: найдено {len(matched_keywords)} уникальных ключевых слов")
        else:
            logger.info(f"Статья не соответствует IT-тематике: найдено только {len(matched_keywords)} уникальных ключевых слов")
        
        return is_related
    
    def get_full_article_content(self, url):
        """Синхронное получение полного текста статьи по URL"""
        if not url:
            logger.warning("Получен пустой URL для скрапинга")
            return ""
            
        # Проверка, был ли URL уже обработан
        if self.is_url_processed(url):
            logger.info(f"URL уже был обработан ранее: {url}")
            return ""
            
        domain = urlparse(url).netloc
        logger.info(f"Попытка получить полный текст статьи с домена {domain}: {url}")
        
        for attempt in range(self.retry_count):
            try:
                response = requests.get(url, headers=self.headers, timeout=self.timeout)
                
                if response.status_code != 200:
                    logger.warning(f"Ошибка HTTP при запросе {url}: {response.status_code}")
                    if attempt < self.retry_count - 1:
                        time.sleep(self.retry_delay)
                        continue
                    self.mark_url_processed(url, is_it_related=False)
                    return ""
                
                # Получение HTML-контента
                html_content = response.text
                soup = BeautifulSoup(html_content, 'html.parser')
                
                # Удаление ненужных элементов
                for tag in soup.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe', 'noscript']):
                    tag.decompose()
                
                # Извлечение заголовка
                title_element = soup.find('title')
                title = title_element.get_text() if title_element else ""
                
                # Извлечение основного контента в зависимости от домена
                article_text = self._extract_content_by_domain(soup, domain)
                
                if article_text:
                    # Проверка на соответствие IT-тематике
                    if self.is_it_related(title, article_text):
                        logger.info(f"Успешно получен текст IT-статьи ({len(article_text)} символов)")
                        # Отмечаем URL как обработанный и релевантный
                        self.mark_url_processed(url, is_it_related=True)
                        return article_text
                    else:
                        logger.info(f"Статья не соответствует IT-тематике: {url}")
                        # Отмечаем URL как обработанный, но не релевантный
                        self.mark_url_processed(url, is_it_related=False)
                        return ""
                else:
                    logger.warning(f"Не удалось извлечь текст статьи с домена {domain}")
                    fallback_content = self._extract_fallback_content(soup)
                    
                    # Проверка на соответствие IT-тематике
                    if fallback_content and self.is_it_related(title, fallback_content):
                        logger.info(f"Успешно получен текст IT-статьи через запасной метод ({len(fallback_content)} символов)")
                        # Отмечаем URL как обработанный и релевантный
                        self.mark_url_processed(url, is_it_related=True)
                        return fallback_content
                    else:
                        # Отмечаем URL как обработанный, но не релевантный
                        self.mark_url_processed(url, is_it_related=False)
                        return ""
            
            except requests.Timeout:
                logger.error(f"Таймаут при запросе {url}. Попытка {attempt+1} из {self.retry_count}")
                if attempt < self.retry_count - 1:
                    time.sleep(self.retry_delay)
                else:
                    self.mark_url_processed(url, is_it_related=False)
                    return ""
            
            except Exception as e:
                logger.error(f"Непредвиденная ошибка при скрапинге {url}: {e}")
                if attempt < self.retry_count - 1:
                    time.sleep(self.retry_delay)
                else:
                    self.mark_url_processed(url, is_it_related=False)
                    return ""
        
        return ""
        
    async def get_full_article_content_async(self, url):
        """Асинхронное получение полного текста статьи по URL"""
        if not url:
            logger.warning("Получен пустой URL для скрапинга")
            return ""
        
        # Проверка, был ли URL уже обработан
        if self.is_url_processed(url):
            logger.info(f"URL уже был обработан ранее: {url}")
            return ""
        
        domain = urlparse(url).netloc
        logger.info(f"Попытка получить полный текст статьи с домена {domain}: {url}")
        
        session = await self.get_session()
        
        for attempt in range(self.retry_count):
            try:
                async with session.get(url, timeout=self.timeout) as response:
                    if response.status != 200:
                        logger.warning(f"Ошибка HTTP при запросе {url}: {response.status}")
                        if attempt < self.retry_count - 1:
                            await asyncio.sleep(self.retry_delay)
                            continue
                        self.mark_url_processed(url, is_it_related=False)
                        return ""
                    
                    # Получение HTML-контента
                    html_content = await response.text()
                    soup = BeautifulSoup(html_content, 'html.parser')
                    
                    # Удаление ненужных элементов
                    for tag in soup.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe', 'noscript']):
                        tag.decompose()
                    
                    # Извлечение заголовка
                    title_element = soup.find('title')
                    title = title_element.get_text() if title_element else ""
                    
                    # Извлечение основного контента в зависимости от домена
                    article_text = self._extract_content_by_domain(soup, domain)
                    
                    if article_text:
                        # Проверка на соответствие IT-тематике
                        if self.is_it_related(title, article_text):
                            logger.info(f"Успешно получен текст IT-статьи ({len(article_text)} символов)")
                            # Отмечаем URL как обработанный и релевантный
                            self.mark_url_processed(url, is_it_related=True)
                            return article_text
                        else:
                            logger.info(f"Статья не соответствует IT-тематике: {url}")
                            # Отмечаем URL как обработанный, но не релевантный
                            self.mark_url_processed(url, is_it_related=False)
                            return ""
                    else:
                        logger.warning(f"Не удалось извлечь текст статьи с домена {domain}")
                        fallback_content = self._extract_fallback_content(soup)
                        
                        # Проверка на соответствие IT-тематике
                        if fallback_content and self.is_it_related(title, fallback_content):
                            logger.info(f"Успешно получен текст IT-статьи через запасной метод ({len(fallback_content)} символов)")
                            # Отмечаем URL как обработанный и релевантный
                            self.mark_url_processed(url, is_it_related=True)
                            return fallback_content
                        else:
                            # Отмечаем URL как обработанный, но не релевантный
                            self.mark_url_processed(url, is_it_related=False)
                            return ""
            
            except asyncio.TimeoutError:
                logger.error(f"Таймаут при запросе {url}. Попытка {attempt+1} из {self.retry_count}")
                if attempt < self.retry_count - 1:
                    await asyncio.sleep(self.retry_delay)
                else:
                    self.mark_url_processed(url, is_it_related=False)
                    return ""
            
            except Exception as e:
                logger.error(f"Непредвиденная ошибка при скрапинге {url}: {e}")
                if attempt < self.retry_count - 1:
                    await asyncio.sleep(self.retry_delay)
                else:
                    self.mark_url_processed(url, is_it_related=False)
                    return ""
        
        return ""
    
    def _extract_content_by_domain(self, soup, domain):
        """Извлечение контента в зависимости от домена"""
        # Расширенные селекторы для популярных IT-новостных сайтов
        article_selectors = {
            'techcrunch.com': ['article', '.article-content', '.article__content'],
            'theverge.com': ['article', '.c-entry-content', '.l-col__main'],
            'wired.com': ['article', '.body__inner-container', '.content'],
            'venturebeat.com': ['article', '.article-content', '.content'],
            'zdnet.com': ['article', '.article-body', '.storyBody'],
            'cnet.com': ['article', '.article-main-body', '.speakableTextP1'],
            'engadget.com': ['article', '.article-text', '.o-article_block'],
            'arstechnica.com': ['article', '.article-content', '.article-guts'],
            'thenextweb.com': ['article', '.post-body', '.c-post-content'],
            'hackernoon.com': ['article', '.story-content', '.content-wrapper'],
            'dev.to': ['article', '.article-body', '.crayons-article__body'],
            'medium.com': ['article', '.section-content', '.section-inner'],
            'infoworld.com': ['article', '.article-body', '.bodee'],
            'techradar.com': ['article', '.content-wrapper', '.text-copy'],
            'towardsdatascience.com': ['article', '.section-content', '.section-inner'],
            'stackoverflow.blog': ['article', '.post-content', '.blog-content'],
            'smashingmagazine.com': ['article', '.article__content', '.entry-content'],
            'technologyreview.com': ['article', '.contentArticleBody', '.gated-article-body'],
            'techrepublic.com': ['article', '.article-main', '.content-article'],
            'computerworld.com': ['article', '.article-body', '.deck'],
            # Добавление новых популярных IT-сайтов
            'github.blog': ['article', '.post-content', '.markdown-body'],
            'stackoverflow.blog': ['article', '.post-content', '.blog-content'],
            'aws.amazon.com/blogs': ['article', '.blog-post', '.aws-blog-post-content'],
            'cloud.google.com/blog': ['article', '.devsite-article-body', '.devsite-article-content'],
            'azure.microsoft.com/blog': ['article', '.blog-content', '.blog-post-content'],
            'developer.mozilla.org': ['article', '.article', '.article__content'],
            'css-tricks.com': ['article', '.article-content', '.entry-content'],
            'freecodecamp.org': ['article', '.post-content', '.post-full-content'],
            'hackernoon.com': ['article', '.story-content', '.content-wrapper'],
            'producthunt.com': ['div.content', '.description', '.content-container']
        }
        
        # Проверка на соответствие известным доменам
        for known_domain, selectors in article_selectors.items():
            if known_domain in domain:
                for selector in selectors:
                    article = soup.select_one(selector)
                    if article:
                        return self._clean_text(article.get_text())
        
        # Общие селекторы для неизвестных доменов
        common_selectors = [
            'article', '.article', '.post', '.content', '.entry-content',
            '.post-content', '.article-content', '.story-content', '.news-content',
            'main', '#main-content', '#content', '.main-content', '.blog-post',
            '.blog-content', '.entry', '.post-body', '.post-text', '.single-post',
            '.page-content', '.article-body', '.article-text', '.story', '.story-body',
            # Добавление новых общих селекторов
            '.markdown-body', '.blog-post-content', '.blog-entry', '.post-container',
            '.article-container', '.content-container', '.post-wrapper', '.article-wrapper',
            '.blog-post-body', '.post-content-body', '.article-content-body'
        ]
        
        for selector in common_selectors:
            article = soup.select_one(selector)
            if article:
                return self._clean_text(article.get_text())
        
        return ""
    
    def _extract_fallback_content(self, soup):
        """Резервный метод извлечения контента, если специфичные селекторы не сработали"""
        # Поиск всех параграфов
        paragraphs = soup.find_all('p')
        if paragraphs:
            # Фильтрация коротких параграфов (менее 30 символов)
            valid_paragraphs = [p.get_text() for p in paragraphs if len(p.get_text()) > 30]
            if valid_paragraphs:
                return self._clean_text("\n\n".join(valid_paragraphs))
        
        # Если параграфы не найдены, извлекаем весь текст из body
        body = soup.find('body')
        if body:
            return self._clean_text(body.get_text())
        
        return ""
    
    def _clean_text(self, text):
        """Очистка текста от лишних пробелов и переносов строк"""
        if not text:
            return ""
            
        # Удаление лишних пробелов и переносов строк
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        cleaned_text = '\n\n'.join(lines)
        
        # Удаление повторяющихся пробелов
        cleaned_text = re.sub(r'\s+', ' ', cleaned_text)
        
        # Удаление повторяющихся знаков пунктуации
        cleaned_text = re.sub(r'([.,!?;:])+', r'\1', cleaned_text)
        
        # Удаление HTML-сущностей
        cleaned_text = re.sub(r'&[a-zA-Z]+;', ' ', cleaned_text)
        
        return cleaned_text.strip()
    
    async def process_urls_batch(self, urls, max_concurrent=5):
        """Асинхронная обработка пакета URL"""
        if not urls:
            return []
        
        logger.info(f"Начало асинхронной обработки {len(urls)} URL")
        
        # Фильтрация URL, которые уже были обработаны
        urls_to_process = []
        for url in urls:
            if not self.is_url_processed(url):
                urls_to_process.append(url)
            else:
                logger.debug(f"URL пропущен (уже обработан): {url}")
        
        if not urls_to_process:
            logger.info("Все URL уже были обработаны ранее")
            return []
        
        logger.info(f"Обработка {len(urls_to_process)} новых URL")
        
        # Ограничение количества одновременных запросов
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def process_with_semaphore(url):
            async with semaphore:
                content = await self.get_full_article_content_async(url)
                return {"url": url, "content": content}
        
        # Создание задач для каждого URL
        tasks = [process_with_semaphore(url) for url in urls_to_process]
        
        # Выполнение всех задач и сбор результатов
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Обработка результатов
        processed_results = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Ошибка при обработке URL: {result}")
                continue
            
            if result["content"]:  # Если контент не пустой
                processed_results.append(result)
        
        logger.info(f"Завершена асинхронная обработка URL. Успешно обработано: {len(processed_results)} из {len(urls_to_process)}")
        return processed_results