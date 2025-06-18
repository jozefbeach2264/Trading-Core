from secure_fetcher import fetch_private

def test_ping():
    result = fetch_private("/fapi/v1/ping")
    print("Ping:", result)

if __name__ == "__main__":
    test_ping()