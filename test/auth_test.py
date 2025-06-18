from secure_fetcher import fetch_private

def test_auth():
    balance = fetch_private("/fapi/v1/account")
    print("Account Info:", balance)

if __name__ == "__main__":
    test_auth()