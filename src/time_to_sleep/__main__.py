import uvicorn


def main() -> None:
    uvicorn.run("time_to_sleep.api:app", host="127.0.0.1", port=4141, reload=False)


if __name__ == "__main__":
    main()
