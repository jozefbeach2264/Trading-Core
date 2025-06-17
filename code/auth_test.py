if __name__ == "__main__":
    from ping_test import ping
    success = ping()
    print("Ping Successful" if success else "Ping Failed")