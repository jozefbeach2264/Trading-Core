import logging

logger = logging.getLogger(__name__)

def calculate_net_roi(
    entry_price: float, 
    exit_price: float, 
    direction: str, 
    leverage: int, 
    fee_rate_taker: float
) -> float:
    """
    Calculates the net ROI of a trade after accounting for taker fees on entry and exit.

    Args:
        entry_price (float): The entry price of the trade.
        exit_price (float): The exit price of the trade.
        direction (str): "LONG" or "SHORT".
        leverage (int): The leverage used for the trade.
        fee_rate_taker (float): The base fee rate for a taker order (e.g., 0.08).

    Returns:
        float: The net ROI as a decimal (e.g., 0.05 for 5%).
    """
    if entry_price == 0:
        logger.error("Cannot calculate ROI with zero entry price.")
        return 0.0

    # Calculate gross PnL ratio
    if direction.upper() == "LONG":
        pnl_ratio = (exit_price - entry_price) / entry_price
    elif direction.upper() == "SHORT":
        pnl_ratio = (entry_price - exit_price) / entry_price
    else:
        logger.error(f"Invalid trade direction for ROI calculation: {direction}")
        return 0.0

    gross_roi = pnl_ratio * leverage

    # Calculate total fee percentage based on the formula: (T1 + T2) * Leverage
    # Where T1 and T2 are the entry and exit taker fee rates.
    total_fee_percentage = (fee_rate_taker / 100) * 2 * leverage
    
    net_roi = gross_roi - total_fee_percentage

    logger.debug(
        f"ROI Calculation: Gross ROI {gross_roi:.4%}, "
        f"Total Fees {total_fee_percentage:.4%}, "
        f"Net ROI {net_roi:.4%}"
    )

    return net_roi
