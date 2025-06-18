from secure_fetcher import fetch_private

def test_order_placement():
    params = {
        "symbol": "ETHUSDT",
        "side": "BUY",
        "type": "MARKET",
        "quantity": 0.01
    }
    result = fetch_private("/fapi/v1/order", params, method="POST")
    print("Order Response:", result)

if __name__ == "__main__":
    test_order_placement()