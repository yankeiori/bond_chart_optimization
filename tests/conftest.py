from app import app
from app.frontend.layout import create_root_layout

# main.py と同じくレイアウトを設定しておく（Dash 4.5 以降は未設定だと最初のリクエストで落ちる）
app.layout = create_root_layout
