"""
Script to run the daily BSE announcement pipeline.
Can be scheduled to run daily after market hours.
"""
import sys
from pathlib import Path
from datetime import date

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.db.sessions import get_db
from app.core.logging_utils import get_logger
from app.services.announcement_workflow import run_daily_announcement_pipeline
import json

logger = get_logger(__name__)


def main():
    """Run the daily announcement pipeline."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Run BSE announcement pipeline")
    parser.add_argument(
        "--date",
        type=str,
        help="Date to process (YYYY-MM-DD), defaults to today",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file path for JSON results (optional)",
    )
    
    args = parser.parse_args()
    
    # Parse date
    target_date = date.today()
    if args.date:
        try:
            target_date = date.fromisoformat(args.date)
        except ValueError:
            logger.error(f"Invalid date format: {args.date}. Use YYYY-MM-DD")
            sys.exit(1)
    
    logger.info(f"Running announcement pipeline for {target_date}")
    
    # Get database session
    db = next(get_db())
    
    try:
        # Run pipeline
        result = run_daily_announcement_pipeline(db=db, target_date=target_date)
        
        # Print summary
        summary = result.get("summary", {})
        logger.info("=" * 60)
        logger.info("PIPELINE SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Date: {target_date}")
        logger.info(f"Total announcements scraped: {summary.get('total_announcements', 0)}")
        logger.info(f"High-volatility announcements: {summary.get('high_vol_count', 0)}")
        logger.info(f"Stocks researched: {summary.get('researched_count', 0)}")
        logger.info(f"Trade-ready recommendations: {summary.get('trade_ready_count', 0)}")
        logger.info("=" * 60)
        
        # Print trade recommendations
        trade_recs = result.get("trade_recommendations", [])
        if trade_recs:
            logger.info("\nTRADE-READY RECOMMENDATIONS:")
            logger.info("-" * 60)
            for idx, rec in enumerate(trade_recs, 1):
                final_rec = rec.get("final_recommendation", {})
                announcement = rec.get("announcement", {})
                
                logger.info(f"\n{idx}. {rec.get('symbol')}")
                logger.info(f"   Headline: {announcement.get('headline', '')[:80]}...")
                logger.info(f"   Direction: {final_rec.get('direction', 'neutral')}")
                logger.info(f"   Confidence: {final_rec.get('confidence_score', 0)}/100")
                logger.info(f"   Strategy: {final_rec.get('suggested_strategy', '')}")
        else:
            logger.info("\nNo trade-ready recommendations found.")
        
        # Print errors if any
        errors = result.get("errors", [])
        if errors:
            logger.warning(f"\nErrors encountered: {len(errors)}")
            for error in errors:
                logger.warning(f"  - {error}")
        
        # Save to file if requested
        if args.output:
            output_path = Path(args.output)
            with open(output_path, "w") as f:
                json.dump(result, f, indent=2, default=str)
            logger.info(f"\nResults saved to {output_path}")
        
        logger.info("\nPipeline completed successfully!")
        
    except Exception as e:
        logger.error(f"Pipeline failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()

