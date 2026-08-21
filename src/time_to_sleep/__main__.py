import os
import uvicorn
from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    port = int(os.environ.get("PORT", 4141))
    uvicorn.run("time_to_sleep.api:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
