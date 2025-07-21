import os
from flask import Flask

app = Flask(__name__)

# … ваши маршруты и хендлеры …

if __name__ == "__main__":
    # Host 0.0.0.0, порт берётся из переменной окружения PORT (которая выставляется в контейнере Render).
    # Если переменная не задана, используется 5000.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
