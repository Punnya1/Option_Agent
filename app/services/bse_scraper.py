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


# High-volatility categories that drive options trading (put/call)
HIGH_VOLATILITY_CATEGORIES = [
    "result", "quarter", "q1", "q2", "q3", "q4", "earnings", "financial",
    "order", "contract", "tender", "award", "loi", "mou",
    "merger", "acquisition", "buyback", "dividend", "bonus", "split",
    "fund raising", "qip", "fpo", "rights issue",
    "regulatory", "sebi", "approval", "license",
    "expansion", "capacity", "project", "commissioning",
]


def _is_high_volatility_category(category: Optional[str], headline: Optional[str]) -> bool:
    """
    Check if an announcement category or headline indicates high volatility potential.
    These are the types that drive put/call options trading.
    
    Returns True if the announcement is likely to cause significant price movement
    (suitable for put/call options trading).
    """
    if not category and not headline:
        return False
    
    combined = f"{category or ''} {headline or ''}".lower()
    
    # Check if category or headline contains high-volatility keywords
    for keyword in HIGH_VOLATILITY_CATEGORIES:
        if keyword.lower() in combined:
            return True
    
    return False


# BSE Category values (from the dropdown)
BSE_CATEGORIES = [
    "AGM/EGM",
    "Board Meeting",
    "Company Update",
    "Corp. Action",
    "Insider Trading / SAST",
    "New Listing",
    "Result",
    "Integrated Filing",
    "Others",
]


def _extract_announcements_from_page(page: Page, category: str) -> List[Dict[str, Any]]:
    """
    Extract announcements from the current page state.
    This is a helper function used after form submission.
    
    Args:
        page: Playwright page object
        category: Category name for logging
        
    Returns:
        List of announcement dictionaries
    """
    announcements = []
    
    try:
        # Try AngularJS scope extraction first
        js_result = page.evaluate("""
            () => {
                var announcements = [];
                try {
                    var appElement = document.querySelector('[ng-app]') || document.body;
                    var scope = angular.element(appElement).scope();
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
            logger.info(f"  ✓ Extracted {len(js_result)} announcements from {category} category")
            return js_result
        else:
            logger.debug(f"  No announcements found in AngularJS scope for {category}")
            return []
    except Exception as e:
        logger.debug(f"  AngularJS extraction failed for {category}: {e}")
        return []


def scrape_bse_announcements(
    page: Page,
    target_date: Optional[date] = None,
    max_pages: int = 10,
    filter_high_volatility: bool = True
) -> List[Dict[str, Any]]:
    """
    Scrape corporate announcements from BSE website.
    
    NEW APPROACH:
    1. Navigate to page and set up form (dates, segment)
    2. Iterate through EACH category (AGM/EGM, Board Meeting, Result, etc.)
    3. For each category: select it, submit, extract announcements
    4. Combine all announcements from all categories
    5. Return combined list (will be prioritized/ranked later before LLM)
    
    PREVIOUS APPROACH (what it was doing before):
    - Navigated to page
    - Set dates and segment
    - Left category as default ("--Select Category--" which might show all)
    - Clicked Submit once
    - Extracted all announcements from single submission
    - This assumed leaving category as default would show all categories
    
    Args:
        page: Playwright page object
        target_date: Date to scrape announcements for (defaults to today)
        max_pages: Maximum number of pages to scrape (not used currently)
        filter_high_volatility: If True, filter by high-volatility keywords (applied after collection)
        
    Returns:
        List of announcement dictionaries with symbol, headline, date, url, etc.
    """
    if target_date is None:
        target_date = date.today()
    
    logger.info(f"Scraping BSE announcements for date: {target_date}")
    logger.info("NEW APPROACH: Iterating through each category to collect all announcements")
    
    base_url = "https://www.bseindia.com/corporates/ann.html"
    all_announcements = []  # Will collect from all categories
    
    try:
        # Navigate to BSE corporate announcements page
        logger.info(f"Navigating to BSE announcements page: {base_url}")
        page.goto(base_url, wait_until="networkidle", timeout=30000)
        logger.info("Page loaded, waiting for form elements...")
        page.wait_for_timeout(2000)
        
        # Calculate date range
        from_date = target_date
        to_date = target_date
        from_date_str = from_date.strftime("%d/%m/%Y")
        to_date_str = to_date.strftime("%d/%m/%Y")
        
        logger.info(f"Setting date range: From {from_date_str} to {to_date_str}")
        
        # Set From Date
        try:
            page.wait_for_selector("#txtFromDt", timeout=10000)
            page.fill("#txtFromDt", from_date_str)
            logger.info(f"✓ Set From Date to: {from_date_str}")
            page.wait_for_timeout(500)
            
            # Close datepicker if it's open (click outside or press Escape)
            try:
                # Try to close datepicker by clicking outside or pressing Escape
                page.keyboard.press("Escape")
                page.wait_for_timeout(200)
            except:
                pass
        except Exception as e:
            logger.warning(f"Could not set From Date: {e}")
        
        # Set To Date
        try:
            page.wait_for_selector("#txtToDt", timeout=10000)
            page.fill("#txtToDt", to_date_str)
            logger.info(f"✓ Set To Date to: {to_date_str}")
            page.wait_for_timeout(500)
            
            # Close datepicker if it's open
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(200)
            except:
                pass
        except Exception as e:
            logger.warning(f"Could not set To Date: {e}")
        
        def _select_equity_fno_segment():
            """Helper function to select Equity F&O segment - call before each category submission."""
            try:
                page.wait_for_selector("#ddlAnnType", timeout=10000)
                page.select_option("#ddlAnnType", value="EQFO")
                logger.debug("  ✓ Re-selected 'Equity F&O' segment (value: EQFO)")
                page.wait_for_timeout(500)
                return True
            except Exception as e:
                logger.debug(f"  Could not select 'Equity F&O' segment via select_option: {e}")
                # Try JavaScript fallback
                try:
                    page.evaluate("""
                        () => {
                            var select = document.querySelector('#ddlAnnType');
                            if (select) {
                                select.value = 'EQFO';
                                var event = new Event('change', { bubbles: true });
                                select.dispatchEvent(event);
                            }
                        }
                    """)
                    logger.debug("  ✓ Re-selected 'Equity F&O' segment via JavaScript")
                    page.wait_for_timeout(500)
                    return True
                except Exception as js_error:
                    logger.warning(f"  JavaScript fallback also failed: {js_error}")
                    return False
        
        # Select "Equity F&O" segment initially
        _select_equity_fno_segment()
        logger.info("✓ Selected 'Equity F&O' segment (value: EQFO)")
        
        # Now iterate through EACH category
        logger.info(f"Iterating through {len(BSE_CATEGORIES)} categories...")
        category_selector = "#ddlPeriod"
        
        for category_idx, category_value in enumerate(BSE_CATEGORIES, 1):
            try:
                logger.info(f"[{category_idx}/{len(BSE_CATEGORIES)}] Processing category: {category_value}")
                
                # CRITICAL: Re-select segment before each category to ensure it persists
                # The form might reset the segment when submitting, so we need to set it again
                _select_equity_fno_segment()
                
                # Select the category
                try:
                    page.wait_for_selector(category_selector, timeout=10000)
                    page.select_option(category_selector, label=category_value)
                    logger.info(f"  ✓ Selected category: {category_value}")
                    page.wait_for_timeout(1000)  # Wait for AngularJS to update
                except Exception as e:
                    logger.warning(f"  Could not select category {category_value}: {e}")
                    continue
                
                # Click Submit button
                # The datepicker overlay is blocking clicks, so we need to:
                # 1. Close/hide the datepicker
                # 2. Use JavaScript to trigger submit directly (bypasses click blocking)
                try:
                    # Strategy 1: Use JavaScript to directly call Angular's fn_submit() function
                    # This bypasses the datepicker blocking issue entirely
                    try:
                        logger.info(f"  Attempting to submit via JavaScript for {category_value}...")
                        result = page.evaluate("""
                            () => {
                                // First, hide/close any open datepickers
                                var datepickers = document.querySelectorAll('.ui-datepicker, #ui-datepicker-div');
                                for (var i = 0; i < datepickers.length; i++) {
                                    datepickers[i].style.display = 'none';
                                }
                                
                                // Get AngularJS scope and call fn_submit()
                                try {
                                    var appElement = document.querySelector('[ng-app]') || document.body;
                                    var scope = angular.element(appElement).scope();
                                    if (scope && scope.fn_submit) {
                                        scope.$apply(function() {
                                            scope.fn_submit();
                                        });
                                        return true;
                                    }
                                } catch (e) {
                                    console.log('AngularJS submit failed:', e);
                                }
                                return false;
                            }
                        """)
                        if result:
                            logger.info(f"  ✓ Triggered Submit for {category_value} (via JavaScript)")
                            submit_clicked = True
                        else:
                            logger.debug("  JavaScript submit: Could not find AngularJS scope or fn_submit function")
                            submit_clicked = False
                    except Exception as e1:
                        logger.debug(f"  JavaScript submit failed: {e1}")
                        submit_clicked = False
                    
                    # Strategy 2: If JavaScript didn't work, try clicking with datepicker hidden
                    if not submit_clicked:
                        try:
                            # Hide datepicker first
                            page.evaluate("""
                                () => {
                                    var datepickers = document.querySelectorAll('.ui-datepicker, #ui-datepicker-div');
                                    for (var i = 0; i < datepickers.length; i++) {
                                        datepickers[i].style.display = 'none';
                                    }
                                }
                            """)
                            page.wait_for_timeout(300)
                            
                            # Press Escape to ensure datepicker is closed
                            page.keyboard.press("Escape")
                            page.wait_for_timeout(300)
                            
                            # Use specific selector
                            submit_selector = 'input[name="submit"][ng-click="fn_submit()"]'
                            page.wait_for_selector(submit_selector, timeout=5000)
                            
                            # Scroll button into view
                            page.evaluate("""
                                () => {
                                    var btn = document.querySelector('input[name="submit"][ng-click="fn_submit()"]');
                                    if (btn) {
                                        btn.scrollIntoView({ behavior: 'instant', block: 'center' });
                                    }
                                }
                            """)
                            page.wait_for_timeout(500)
                            
                            # Click with force to bypass actionability
                            page.click(submit_selector, force=True, timeout=10000)
                            logger.info(f"  ✓ Clicked Submit for {category_value} (via click with datepicker hidden)")
                            submit_clicked = True
                        except Exception as e2:
                            logger.debug(f"  Click submit failed: {e2}")
                    
                    if not submit_clicked:
                        raise Exception("All submit strategies failed")
                    
                    # Wait for results to load
                    logger.info(f"  Waiting for results to load for {category_value}...")
                    page.wait_for_timeout(3000)  # Give AngularJS time to process
                    
                    # Wait for table to appear (with longer timeout)
                    try:
                        page.wait_for_selector("table tbody tr", timeout=15000)
                        logger.info(f"  ✓ Results loaded for {category_value}")
                    except:
                        logger.warning(f"  Results table not found for {category_value}, but continuing...")
                        
                except Exception as e:
                    logger.warning(f"  Could not submit or load results for {category_value}: {e}")
                    continue
                
                # Extract announcements from this category
                category_announcements = _extract_announcements_from_page(page, category_value)
                
                if category_announcements:
                    # Process and add to all_announcements
                    for ann_data in category_announcements:
                        try:
                            headline = ann_data.get("headline", "").strip()
                            if not headline or len(headline) < 10:
                                continue
                            
                            scrip_code = ann_data.get("scrip_code")
                            company_name = ann_data.get("company_name")
                            category = ann_data.get("category") or category_value
                            
                            # Parse date
                            event_date = target_date
                            news_date = ann_data.get("news_date")
                            if news_date:
                                if isinstance(news_date, str):
                                    parsed = _parse_date(news_date)
                                    if parsed:
                                        event_date = parsed
                                elif isinstance(news_date, (int, float)):
                                    try:
                                        event_date = datetime.fromtimestamp(news_date / 1000).date()
                                    except:
                                        pass
                            
                            # Extract symbol
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
                                ann_dict = {
                                    "symbol": symbol.upper() if symbol else None,
                                    "scrip_code": str(scrip_code) if scrip_code else None,
                                    "headline": headline[:500],
                                    "event_date": event_date,
                                    "category": category,
                                    "company_name": company_name,
                                    "url": None,
                                }
                                all_announcements.append(ann_dict)
                        except Exception as e:
                            logger.warning(f"  Error processing announcement from {category_value}: {e}")
                            continue
                
                # Small delay between categories to avoid rate limiting
                page.wait_for_timeout(1000)
                
            except Exception as e:
                logger.warning(f"Error processing category {category_value}: {e}")
                continue
        
        logger.info(f"✓ Collected {len(all_announcements)} total announcements from all categories")
        
        # Now filter for high-volatility if requested (this happens AFTER collecting from all categories)
        announcements = []
        filtered_count = 0
        
        if filter_high_volatility:
            logger.info(f"Filtering {len(all_announcements)} announcements for high-volatility categories...")
            for ann in all_announcements:
                category = ann.get("category", "")
                headline = ann.get("headline", "")
                if _is_high_volatility_category(category, headline):
                    announcements.append(ann)
                else:
                    filtered_count += 1
            logger.info(
                f"✓ Filtered to {len(announcements)} high-volatility announcements "
                f"(filtered out {filtered_count} low-volatility)"
            )
        else:
            announcements = all_announcements
        
        # Summary logging
        if filter_high_volatility:
            if filtered_count > 0:
                logger.info(
                    f"✓ Final result: {len(announcements)} high-volatility announcements "
                    f"(from {len(all_announcements)} total, filtered out {filtered_count})"
                )
            else:
                logger.info(
                    f"✓ Final result: {len(announcements)} high-volatility announcements "
                    f"(all {len(all_announcements)} matched high-volatility criteria)"
                )
        else:
            logger.info(f"✓ Final result: {len(announcements)} announcements (no filtering applied)")
        
        if len(announcements) == 0:
            logger.warning(
                f"No announcements found! This could mean: "
                f"1) No announcements for the selected date/segment/categories, "
                f"2) Form submissions didn't work, "
                f"3) Page structure changed, or "
                f"4) All announcements were filtered out (if filtering enabled)"
            )
        
        return announcements
        
    except Exception as e:
        logger.error(f"Error scraping BSE announcements: {e}")
        raise


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
            # Filter for high-volatility categories (results, orders, etc.) that drive put/call options
            all_announcements = []
            for days_back in range(lookback_days + 1):
                scrape_date = target_date - timedelta(days=days_back)
                announcements = scrape_bse_announcements(
                    page, 
                    target_date=scrape_date,
                    filter_high_volatility=True  # Only get high-volatility announcements
                )
                all_announcements.extend(announcements)
            
            # Prepare announcements and generate hashes
            # Use a dict to deduplicate by content_hash within the scraped announcements
            # (same announcement might appear in multiple categories)
            announcements_dict = {}  # content_hash -> event
            
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
                
                # Deduplicate: if we've seen this hash before, skip it (same announcement in multiple categories)
                if content_hash in announcements_dict:
                    logger.debug(f"Skipping duplicate announcement within scraped results: {headline[:50]}...")
                    continue
                
                # Create event record (will be inserted if not duplicate in DB)
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
                
                announcements_dict[content_hash] = event
            
            if not announcements_dict:
                logger.info("No valid announcements to insert")
                return 0
            
            # Extract content_hashes for database check
            content_hashes = list(announcements_dict.keys())
            
            # Check which content_hashes already exist in database (bulk check)
            existing_hashes = set(
                db.query(BSEEvent.content_hash)
                .filter(BSEEvent.content_hash.in_(content_hashes))
                .all()
            )
            # Flatten the result set
            existing_hashes = {h[0] for h in existing_hashes}
            
            # Filter out duplicates that already exist in database
            new_announcements = [
                event for content_hash, event in announcements_dict.items()
                if content_hash not in existing_hashes
            ]
            
            if not new_announcements:
                logger.info(f"All {len(announcements_dict)} announcements already exist in database")
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
                skipped_count = len(announcements_dict) - inserted
                logger.info(f"Inserted {inserted} new BSE announcements (skipped {skipped_count} duplicates)")
            else:
                logger.info("No new BSE announcements to insert")
                
        except Exception as e:
            logger.error(f"Error during BSE scraping: {e}")
            db.rollback()
            raise
        finally:
            browser.close()
    
    return inserted

