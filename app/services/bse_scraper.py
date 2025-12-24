"""
BSE Corporate Announcements Scraper using Playwright
"""
import hashlib
from datetime import date, datetime, timedelta
from typing import List, Dict, Any, Optional
import re

from playwright.sync_api import sync_playwright, Page, Browser
from sqlalchemy.orm import Session
from sqlalchemy import exists

from app.core.logging_utils import get_logger
from app.db.models import BSEEvent

logger = get_logger(__name__)


def _generate_content_hash(symbol: str, headline: str, event_date: date) -> str:
    """Generate a unique hash for an event to avoid duplicates."""
    content = f"{symbol}|{headline}|{event_date.isoformat()}"
    return hashlib.md5(content.encode()).hexdigest()


def _parse_date(date_str: str) -> Optional[date]:
    """Parse BSE date format to date object."""
    if not date_str:
        return None
    
    try:
        date_str = date_str.strip()
        
        # BSE formats: "15 Dec 2025", "15-Dec-2025", "15/12/2025", "dd MMM yyyy"
        formats = [
            "%d %b %Y",      # "15 Dec 2025"
            "%d-%b-%Y",      # "15-Dec-2025"
            "%d/%m/%Y",      # "15/12/2025"
            "%d-%m-%Y",      # "15-12-2025"
            "%Y-%m-%d",      # "2025-12-15"
            "%d %B %Y",      # "15 December 2025"
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        
        # Try parsing manually if formats don't work
        if "/" in date_str:
            parts = date_str.split("/")
            if len(parts) == 3:
                try:
                    return date(int(parts[2]), int(parts[1]), int(parts[0]))
                except (ValueError, IndexError):
                    pass
        
        return None
    except Exception as e:
        logger.warning(f"Failed to parse date '{date_str}': {e}")
        return None


def _extract_symbol_from_text(text: str) -> Optional[str]:
    """Extract stock symbol from announcement text."""
    # BSE symbols are typically uppercase, 2-20 chars, alphanumeric
    # Look for patterns like "RELIANCE", "TCS", "INFY" etc.
    # Common pattern: Symbol is often at the start or mentioned explicitly
    text_upper = text.upper()
    
    # Try to find symbol patterns (all caps, 2-20 chars, not common words)
    words = re.findall(r'\b[A-Z]{2,20}\b', text_upper)
    common_words = {'THE', 'AND', 'FOR', 'WITH', 'FROM', 'THIS', 'THAT', 'LIMITED', 'LTD', 'INC', 'CORP'}
    
    for word in words:
        if word not in common_words and len(word) >= 2:
            # Check if it looks like a stock symbol (no special chars, reasonable length)
            if word.isalnum() and 2 <= len(word) <= 20:
                return word
    
    return None


def _get_symbol_from_scrip_code(db: Session, scrip_code: str) -> Optional[str]:
    """
    Map BSE scrip code to stock symbol.
    For now, we'll try to extract from company name or use the scrip code itself.
    In production, you might want a mapping table.
    """
    # TODO: Create a BSE scrip code to symbol mapping table if needed
    # For now, return None and let the extractor try other methods
    return None


def scrape_bse_announcements(
    page: Page,
    target_date: Optional[date] = None,
    max_pages: int = 10
) -> List[Dict[str, Any]]:
    """
    Scrape corporate announcements from BSE website.
    
    The BSE website uses AngularJS to dynamically load announcements.
    We wait for the AngularJS data to load and extract from the rendered table.
    
    Args:
        page: Playwright page object
        target_date: Date to scrape announcements for (defaults to today)
        max_pages: Maximum number of pages to scrape
        
    Returns:
        List of announcement dictionaries with symbol, headline, date, url, etc.
    """
    if target_date is None:
        target_date = date.today()
    
    logger.info(f"Scraping BSE announcements for date: {target_date}")
    
    base_url = "https://www.bseindia.com/corporates/ann.html"
    announcements = []
    
    try:
        # Navigate to BSE corporate announcements page
        page.goto(base_url, wait_until="networkidle", timeout=30000)
        
        # Wait for AngularJS to load and render the table
        page.wait_for_selector("table tbody tr", timeout=15000)
        page.wait_for_timeout(3000)
        
        # Try to extract data directly from AngularJS scope using JavaScript
        # This is more reliable than parsing HTML
        try:
            js_result = page.evaluate("""
                () => {
                    // Try to access AngularJS scope
                    var announcements = [];
                    try {
                        // Get the AngularJS app element
                        var appElement = document.querySelector('[ng-app]') || document.body;
                        var scope = angular.element(appElement).scope();
                        
                        // Access CorpannData.Table from the scope
                        if (scope && scope.CorpannData && scope.CorpannData.Table) {
                            var table = scope.CorpannData.Table;
                            for (var i = 0; i < table.length; i++) {
                                var cann = table[i];
                                announcements.push({
                                    scrip_code: cann.SCRIP_CD || null,
                                    company_name: cann.SLONGNAME || null,
                                    headline: cann.NEWSSUB || '',
                                    category: cann.CATEGORYNAME || null,
                                    news_date: cann.NEWS_DT || null,
                                    submission_date: cann.News_submission_dt || null,
                                    dissemination_date: cann.DissemDT || null
                                });
                            }
                        }
                    } catch (e) {
                        console.log('AngularJS scope access failed:', e);
                    }
                    return announcements;
                }
            """)
            
            if js_result and len(js_result) > 0:
                logger.info(f"Extracted {len(js_result)} announcements from AngularJS scope")
                for ann_data in js_result:
                    try:
                        headline = ann_data.get("headline", "").strip()
                        if not headline or len(headline) < 10:
                            continue
                        
                        scrip_code = ann_data.get("scrip_code")
                        company_name = ann_data.get("company_name")
                        category = ann_data.get("category")
                        
                        # Parse date
                        event_date = target_date
                        news_date = ann_data.get("news_date")
                        if news_date:
                            # news_date might be in various formats
                            if isinstance(news_date, str):
                                parsed = _parse_date(news_date)
                                if parsed:
                                    event_date = parsed
                            elif isinstance(news_date, (int, float)):
                                # Might be a timestamp
                                try:
                                    event_date = datetime.fromtimestamp(news_date / 1000).date()
                                except:
                                    pass
                        
                        # Extract symbol from company name or headline
                        symbol = None
                        if company_name:
                            words = company_name.split()
                            if words:
                                potential_symbol = words[0].upper().strip('.,')
                                if 2 <= len(potential_symbol) <= 20 and potential_symbol.isalnum():
                                    symbol = potential_symbol
                        
                        if not symbol:
                            symbol = _extract_symbol_from_text(headline)
                        
                        if headline and (symbol or scrip_code):
                            announcements.append({
                                "symbol": symbol.upper() if symbol else None,
                                "scrip_code": str(scrip_code) if scrip_code else None,
                                "headline": headline[:500],
                                "event_date": event_date,
                                "category": category,
                                "company_name": company_name,
                                "url": None,  # URL would need to be constructed from scrip_code if needed
                            })
                    except Exception as e:
                        logger.warning(f"Error processing announcement from JS: {e}")
                        continue
        except Exception as e:
            logger.warning(f"Failed to extract from AngularJS scope, falling back to HTML parsing: {e}")
            
            # Fallback to HTML parsing
            rows = page.query_selector_all("table tbody tr")
            logger.info(f"Found {len(rows)} table rows (fallback mode)")
            
            for idx, row in enumerate(rows):
                try:
                    # Extract headline
                    headline_elem = row.query_selector('span[ng-bind-html="cann.NEWSSUB"]')
                    if not headline_elem:
                        first_td = row.query_selector("td:first-child")
                        if first_td:
                            headline_elem = first_td
                        else:
                            continue
                    
                    headline = headline_elem.inner_text().strip()
                    if not headline or len(headline) < 10:
                        continue
                    
                    # Extract from row text
                    row_text = row.inner_text()
                    scrip_code = None
                    scrip_match = re.search(r'Security Code\s*:\s*(\d+)', row_text, re.IGNORECASE)
                    if scrip_match:
                        scrip_code = scrip_match.group(1)
                    
                    company_name = None
                    company_match = re.search(r'Company\s*:\s*([^\n]+)', row_text, re.IGNORECASE)
                    if company_match:
                        company_name = company_match.group(1).strip()
                    
                    category = None
                    category_match = re.search(r'(AGM/EGM|Board Meeting|Company Update|Corp\. Action|Result|Others)', row_text)
                    if category_match:
                        category = category_match.group(1)
                    
                    event_date = target_date
                    date_match = re.search(r'(\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})', row_text, re.IGNORECASE)
                    if date_match:
                        date_str = date_match.group(1)
                        parsed = _parse_date(date_str)
                        if parsed:
                            event_date = parsed
                    
                    symbol = None
                    if company_name:
                        words = company_name.split()
                        if words:
                            potential_symbol = words[0].upper().strip('.,')
                            if 2 <= len(potential_symbol) <= 20 and potential_symbol.isalnum():
                                symbol = potential_symbol
                    
                    if not symbol:
                        symbol = _extract_symbol_from_text(headline)
                    
                    if headline and (symbol or scrip_code):
                        announcements.append({
                            "symbol": symbol.upper() if symbol else None,
                            "scrip_code": scrip_code,
                            "headline": headline[:500],
                            "event_date": event_date,
                            "category": category,
                            "company_name": company_name,
                            "url": None,
                        })
                except Exception as e:
                    logger.warning(f"Error parsing row {idx}: {e}")
                    continue
        
        # Handle pagination if needed
        # BSE has "Prev" and "Next" buttons
        # For now, we'll just get the first page
        # TODO: Add pagination support if needed
        
        logger.info(f"Scraped {len(announcements)} announcements from BSE")
        
    except Exception as e:
        logger.error(f"Error scraping BSE announcements: {e}")
        raise
    
    return announcements


def ingest_bse_announcements(
    db: Session,
    target_date: Optional[date] = None,
    lookback_days: int = 1
) -> int:
    """
    Scrape and ingest BSE corporate announcements into database.
    
    Args:
        db: Database session
        target_date: Date to scrape (defaults to today)
        lookback_days: Number of days to look back (for catching missed announcements)
        
    Returns:
        Number of announcements inserted
    """
    if target_date is None:
        target_date = date.today()
    
    logger.info(f"Ingesting BSE announcements for date: {target_date}, lookback: {lookback_days} days")
    
    # Ensure the bse_events table exists - create it if it doesn't
    try:
        from app.db.sessions import Base, engine
        # Import all models to ensure they're registered with Base.metadata
        from app.db.models import (
            Stock, DailyPrice, OptionChain, News, NewsImpact, 
            DailyCandidate, BSEEvent, ProcessedRun
        )
        # Create the table if it doesn't exist
        BSEEvent.__table__.create(bind=engine, checkfirst=True)
        logger.debug("Verified bse_events table exists")
    except Exception as e:
        logger.error(f"Could not create bse_events table: {e}")
        logger.error("Please run 'python scripts/init_db_script.py' to create all tables")
        raise
    
    inserted = 0
    
    with sync_playwright() as p:
        # Launch browser (headless by default)
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()
        
        try:
            # Scrape for target date and lookback days
            all_announcements = []
            for days_back in range(lookback_days + 1):
                scrape_date = target_date - timedelta(days=days_back)
                announcements = scrape_bse_announcements(page, target_date=scrape_date)
                all_announcements.extend(announcements)
            
            # Prepare announcements and generate hashes
            announcements_to_insert = []
            content_hashes = []
            
            for ann in all_announcements:
                symbol = ann.get("symbol")
                scrip_code = ann.get("scrip_code")
                headline = ann.get("headline")
                event_date = ann.get("event_date")
                
                # Need at least headline and either symbol or scrip_code
                if not headline or not event_date:
                    continue
                if not symbol and not scrip_code:
                    logger.warning(f"Skipping announcement without symbol or scrip_code: {headline[:50]}")
                    continue
                
                # Use scrip_code as fallback identifier if symbol not available
                identifier = symbol or scrip_code
                
                # Generate content hash for deduplication
                content_hash = _generate_content_hash(identifier, headline, event_date)
                content_hashes.append(content_hash)
                
                # Create event record (will be inserted if not duplicate)
                event = BSEEvent(
                    symbol=symbol,
                    scrip_code=ann.get("scrip_code"),
                    headline=headline,
                    category=ann.get("category"),
                    event_date=event_date,
                    published_at=datetime.now(),
                    url=ann.get("url"),
                    source="BSE",
                    content_hash=content_hash,
                )
                
                announcements_to_insert.append((content_hash, event))
            
            if not announcements_to_insert:
                logger.info("No valid announcements to insert")
                return 0
            
            # Check which content_hashes already exist (bulk check)
            existing_hashes = set(
                db.query(BSEEvent.content_hash)
                .filter(BSEEvent.content_hash.in_(content_hashes))
                .all()
            )
            # Flatten the result set
            existing_hashes = {h[0] for h in existing_hashes}
            
            # Filter out duplicates
            new_announcements = [
                event for content_hash, event in announcements_to_insert
                if content_hash not in existing_hashes
            ]
            
            if not new_announcements:
                logger.info(f"All {len(announcements_to_insert)} announcements already exist in database")
                return 0
            
            # Insert new announcements in batches with error handling
            inserted = 0
            batch_size = 50
            current_time = datetime.now()
            
            for i in range(0, len(new_announcements), batch_size):
                batch = new_announcements[i:i + batch_size]
                batch_inserted = 0
                
                for event in batch:
                    # Update published_at to current time for this batch
                    event.published_at = current_time
                    db.add(event)
                    batch_inserted += 1
                
                try:
                    db.commit()
                    inserted += batch_inserted
                    logger.debug(f"Inserted batch of {batch_inserted} announcements")
                except Exception as e:
                    db.rollback()
                    # If batch insert fails, try one by one
                    logger.warning(f"Batch insert failed, trying individual inserts: {e}")
                    for event in batch:
                        try:
                            event.published_at = current_time
                            db.add(event)
                            db.commit()
                            inserted += 1
                        except Exception as individual_error:
                            db.rollback()
                            # Skip duplicates or other errors
                            if "duplicate" in str(individual_error).lower() or "unique" in str(individual_error).lower():
                                logger.debug(f"Skipping duplicate: {event.headline[:50]}...")
                            else:
                                logger.warning(f"Error inserting announcement: {individual_error}")
            
            if inserted > 0:
                logger.info(f"Inserted {inserted} new BSE announcements (skipped {len(announcements_to_insert) - inserted} duplicates)")
            else:
                logger.info("No new BSE announcements to insert")
                
        except Exception as e:
            logger.error(f"Error during BSE scraping: {e}")
            db.rollback()
            raise
        finally:
            browser.close()
    
    return inserted

