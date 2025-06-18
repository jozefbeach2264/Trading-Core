from secure_fetcher import fetch_private

def get_server_time():
    result = fetch_private("/fapi/v1/time")
    print("Server Time:", result)

if __name__ == "__main__":
    get_server_time()