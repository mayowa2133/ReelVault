from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.services.google_drive_service import GoogleDriveService, drive_folder_link


def main() -> None:
    settings = get_settings()
    drive = GoogleDriveService(settings)
    folders = drive.ensure_drive_library_folders()

    print("ReelVault Drive folders are ready.")
    print()
    print("Pillar folders:")
    for pillar, folder_id in folders["pillars"].items():
        print(f"- {pillar}: {drive_folder_link(folder_id)}")

    print()
    print(f"{settings.raw_folder_name} folders:")
    for pillar, folder_id in folders["raw"].items():
        print(f"- {pillar}: {drive_folder_link(folder_id)}")


if __name__ == "__main__":
    main()
