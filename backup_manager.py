
import shutil
import os
from datetime import datetime

def backup_file(filepath):
    if not os.path.exists(filepath):
        return False
    backup_dir = "backups"
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    backup_path = os.path.join(backup_dir, f"{os.path.basename(filepath)}.{timestamp}.bak")
    shutil.copy(filepath, backup_path)
    return True