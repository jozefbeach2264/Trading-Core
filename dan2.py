# dan2.py (Core Side: Trading Reality Core)
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DAN2Support:
    @staticmethod
    def calculate_pressure(data):
        """Calculate execution pressure differential."""
        bids = sum([size for price, size in data["order_book"]["bids"]])
        asks = sum([size for price, size in data["order_book"]["asks"]])
        return (bids - asks) / (bids + asks) if (bids + asks) > 0 else 0

    @staticmethod
    def check_timing_stack(signal):
        """Validate signal timing."""
        timestamp = datetime.fromisoformat(signal["timestamp"])
        return (datetime.utcnow() - timestamp).total_seconds() < 60

if __name__ == "__main__":
    logger.info("DAN2 Support running as part of core system")