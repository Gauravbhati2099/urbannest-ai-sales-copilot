from app.db.session import SessionLocal
from app.modules.chatbot.storage import purge_expired_chat_data


def main() -> None:
    with SessionLocal() as session:
        conversations, messages = purge_expired_chat_data(session)
    print(
        "Purged expired chat data: "
        f"{conversations} conversations and {messages} messages."
    )


if __name__ == "__main__":
    main()
