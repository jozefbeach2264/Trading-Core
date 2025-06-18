from rolling5_engine import Rolling5

if name == "main": r5 = Rolling5() for _ in range(10): entry = random.uniform(2500, 2700) exit = entry + random.uniform(-25, 25) r5.simulate_trade(entry_price=entry, exit_price=exit) time.sleep(1)