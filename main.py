import os
import logging
import requests
from flask import Flask, request
from telegram import Bot, Update, BotCommand
from telegram.ext import Dispatcher, MessageHandler, Filters, CommandHandler, CallbackContext

# --- LẤY TỪ BIẾN MÔI TRƯỜNG CỦA RENDER ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
SIGHTENGINE_API_USER = os.environ.get('SIGHTENGINE_API_USER')
SIGHTENGINE_API_SECRET = os.environ.get('SIGHTENGINE_API_SECRET')
# -----------------------------------------

# Cấu hình logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Khởi tạo Flask app
# Tên biến 'app' là quan trọng, Render (Gunicorn) sẽ tìm nó
app = Flask(__name__)

# Khởi v_token=TELEGRAM_TOKEN)
dispatcher = Dispatcher(bot, None, use_context=True)

# --- Các hàm xử lý của Bot ---

def check_image_with_sightengine(image_url: str) -> dict:
    """Gửi URL ảnh đến Sightengine để kiểm tra AI-generated."""
    api_url = 'https://api.sightengine.com/1.0/check.json'
    params = {
        'models': 'ai-generated',
        'url': image_url,
        'api_user': SIGHTENGINE_API_USER,
        'api_secret': SIGHTENGINE_API_SECRET
    }
    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()  # Ném lỗi nếu request thất bại
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Lỗi khi gọi API Sightengine: {e}")
        return None

def start(update: Update, context: CallbackContext) -> None:
    """Xử lý lệnh /start."""
    user = update.effective_user
    update.message.reply_html(
        f"Chào {user.mention_html()}! 👋\n\nHãy gửi cho tôi một bức ảnh để kiểm tra AI.",
    )

def handle_photo(update: Update, context: CallbackContext) -> None:
    """Xử lý ảnh người dùng gửi."""
    try:
        photo_file = update.message.photo[-1].get_file()
        
        # === DÒNG CODE ĐÚNG (ĐÃ SỬA LẠI VỀ BẢN GỐC) ===
        # .file_path từ get_file() trong thư viện v13 đã là URL đầy đủ
        image_url = photo_file.file_path
        # === KẾT THÚC SỬA LỖI ===

        if not image_url:
            update.message.reply_text("Không thể lấy được ảnh, vui lòng thử lại.")
            return

        waiting_message = update.message.reply_text("Đang phân tích ảnh...")
        
        result = check_image_with_sightengine(image_url)
        
        # Xóa tin nhắn chờ
        context.bot.delete_message(chat_id=waiting_message.chat_id, message_id=waiting_message.message_id)

        if not result:
            update.message.reply_text("Có lỗi xảy ra trong quá trình phân tích (API error).")
            return

        if result.get('status') == 'success':
            ai_info = result.get('ai_generated')
            if ai_info:
                prob_ai = ai_info.get('prob_ai') * 100
                prob_human = ai_info.get('prob_human') * 100
                
                response_text = f"Kết quả phân tích:\n"
                response_text += f"🤖 **{prob_ai:.2f}%** khả năng là do AI tạo ra.\n"
                response_text += f"🧑 **{prob_human:.2f}%** khả năng là ảnh thật."
                
                update.message.reply_text(response_text, parse_mode='Markdown')
            else:
                update.message.reply_text("Không thể phân tích ảnh này (API không trả về kết quả).")
        else:
            error_message = result.get('error', {}).get('message', 'Lỗi không xác định từ Sightengine.')
            update.message.reply_text(f"Phân tích thất bại: {error_message}")
    except Exception as e:
        logger.error(f"Lỗi khi xử lý ảnh: {e}")
        update.message.reply_text("Đã có lỗi nghiêm trọng xảy ra, vui lòng thử lại với ảnh khác.")

# Đăng ký các handler
dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(MessageHandler(Filters.photo, handle_photo))

# --- Phần Webhook và Flask (Giữ nguyên) ---

@app.route('/')
def index():
    """Trang web đơn giản để UptimeRobot 'ping'."""
    return "Bot đang chạy!", 200

@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    """Lắng nghe tín hiệu từ Telegram."""
    json_data = request.get_json(force=True)
    update = Update.de_json(json_data, bot)
    dispatcher.process_update(update)
    return "OK", 200

def set_webhook_on_startup():
    """Tự động set webhook khi khởi động (Phát hiện URL của Render)."""
    webhook_base_url = None
    
    render_url = os.environ.get("RENDER_EXTERNAL_URL")
    if render_url:
        webhook_base_url = render_url
        logger.info(f"Phát hiện đang chạy trên Render: {render_url}")
    else:
        logger.warning("Không thể tự động lấy URL của Render. Webhook chưa được set.")
        return

    webhook_url = f"{webhook_base_url}/{TELEGRAM_TOKEN}"
    
    try:
        response = bot.set_webhook(webhook_url, allowed_updates=["message"])
        if response:
            logger.info(f"Webhook đã được set thành công: {webhook_url}")
            commands = [BotCommand("start", "Bắt đầu cuộc trò chuyện")]
            bot.set_my_commands(commands)
        else:
            logger.error("Set webhook thất bại.")
    except Exception as e:
        logger.error(f"Lỗi khi set webhook: {e}")

# Chạy hàm set_webhook khi ứng dụng khởi động
if TELEGRAM_TOKEN:
    set_webhook_on_startup()
else:
    logger.error("TELEGRAM_TOKEN không được tìm thấy. Bỏ qua set webhook.")
