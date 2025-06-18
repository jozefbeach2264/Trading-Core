class SpoofFilter:
    def __init__(self, depth_threshold=5, volume_drop_pct=10):
        self.depth_threshold = depth_threshold
        self.volume_drop_pct = volume_drop_pct

    def detect_spoof(self, orderbook):
        if not orderbook or "asks" not in orderbook or "bids" not in orderbook:
            return False

        for side in ["asks", "bids"]:
            entries = orderbook[side][:self.depth_threshold]
            vols = [entry[1] for entry in entries]
            if len(vols) < 2:
                continue
            drop = ((vols[0] - vols[-1]) / vols[0]) * 100 if vols[0] > 0 else 0
            if drop >= self.volume_drop_pct:
                return True
        return False