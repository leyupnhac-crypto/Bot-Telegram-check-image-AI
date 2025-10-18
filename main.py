import os
import logging
import requests
from flask import Flask, request
from telegram import Bot, Update, BotCommand
from telegram.ext import Dispatcher, MessageHandler, Filters, CommandHandler, CallbackContext

# --- LẤY TỪ BIẾN MÔI TRƯỜNG CỦA RENDER ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
AIORNOT_API_KEY = os.environ.get('AIORNOT_API_KEY')
# -----------------------------------------

# Cấu hình logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Khởi tạo Flask app
app = Flask(__name__)

# Khởi tạo Bot và Dispatcher
bot = Bot(token=TELEGRAM_TOKEN)
dispatcher = Dispatcher(bot, None, use_context=True)

# --- Các hàm xử lý của Bot ---

def check_image_with_aiornot(image_data: bytes) -> dict:
    """
    Tải DỮ LIỆU ảnh lên AIorNot v2 (Cách "chuẩn nhất").
    """
    api_url = 'https://api.aiornot.com/v2/image/sync'
    
    headers = {
        'Authorization': f"Bearer {AIORNOT_API_KEY}",
        'Accept': 'application/json'
    }
    
    payload_files = {
        'image': image_data
    }

    try:
        response = requests.post(api_url, headers=headers, files=payload_files, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Lỗi khi gọi API AIorNot: {e}")
        return None

def start(update: Update, context: CallbackContext) -> None:
    """Xử lý lệnh /start."""
    user = update.effective_user
    update.message.reply_html(
        f"Chào {user.mention_html()}! 👋\n\nHãy gửi cho tôi một bức ảnh để kiểm tra AI.",
    )

def handle_photo(update: Update, context: CallbackContext) -> None:
    """Xử lý ảnh người dùng gửi (Đã sửa logic đọc kết quả theo log)."""
    try:
        photo_file = update.message.photo[-1].get_file()
        image_bytes = photo_file.download_as_bytearray()

        waiting_message = update.message.reply_text("Đang phân tích ảnh (đang tải lên)...")
        
        result = check_image_with_aiornot(image_bytes)
        
        context.bot.delete_message(chat_id=waiting_message.chat_id, message_id=waiting_message.message_id)

        if not result:
            update.message.reply_text("Có lỗi xảy ra trong quá trình phân tích (API error / Timeout).")
            return

        # Dùng logger.warning để bạn CHẮC CHẮN thấy dòng này trong Log
        logger.warning(f"ĐÃ NHẬN PHẢN HỒI TỪ API: {result}")

        # === SỬA LỖI LOGIC ĐỌC KẾT QUẢ (Theo log của bạn) ===
        report = result.get('report')

        if report:
            # 1. Lấy kết quả AI chính
            ai_info = report.get('ai_generated', {}) # Lấy đối tượng 'ai_generated'
            verdict = ai_info.get('verdict', 'N/A') # Lấy 'verdict' từ bên trong
            ai_score_percent = ai_info.get('ai', {}).get('confidence', 0) * 100 # Lấy 'confidence' từ bên trong 'ai'

            # 2. Lấy nguồn Generator (Phần này không có trong log của bạn, nhưng cứ để dự phòng)
            generator_info = report.get('generator', {})
            generator_name = "Không rõ"
            if generator_info:
                try:
                    generator_name = max(generator_info.items(), key=lambda item: item[1].get('confidence', 0))[0]
                    generator_name = generator_name.replace("_", " ").title()
                except ValueError:
                    generator_name = "Không rõ"

            # 3. Lấy kết quả Deepfake (Đọc 'is_detected')
            deepfake_detected = report.get('deepfake', {}).get('is_detected', None)
            deepfake_verdict = "Phát hiện" if deepfake_detected else "Không"

            # 4. Lấy kết quả NSFW (Đọc 'is_detected')
            nsfw_detected = report.get('nsfw', {}).get('is_detected', None)
            nsfw_verdict = "Phát hiện" if nsfw_detected else "Không"

            # 5. Lấy kết quả Quality (Đọc 'is_detected')
            quality_detected = report.get('quality', {}).get('is_detected', None)
            quality_verdict = "Tốt" if quality_detected else "Thấp" # Giả định 'is_detected': True là chất lượng tốt
            
            # === KẾT THÚC SỬA LỖI LOGIC ===

            response_text = ""
            if verdict == 'ai':
                response_text = f"Kết quả: **Ảnh này là do AI tạo ra** 🤖\n"
                response_text += f"Điểm AI tổng quát: **{ai_score_percent:.1f}%**\n"
                response_text += f"Nguồn AI (Ước tính): **{generator_name}**\n"
            elif verdict == 'human' or verdict == 'clear': # 'clear' là từ code cũ, 'human' là từ log
                response_text = f"Kết quả: **Đây là ảnh thật** (do người chụp) 🧑\n"
                response_text += f"Điểm AI tổng quát: **{ai_score_percent:.1f}%**\n"
            else:
                response_text = f"Không rõ kết quả (Verdict: {verdict})\n"

            response_text += "\n--- Chi tiết khác ---\n"
            response_text += f"Deepfake: **{deepfake_verdict}**\n"
            response_text += f"Nội dung NSFW: **{nsfw_verdict}**\n"
            response_text += f"Chất lượng ảnh: **{quality_verdict}**"

            update.message.reply_text(response_text, parse_mode='Markdown')
        
        else:
            update.message.reply_text("Không thể phân tích ảnh này (API không trả về kết quả 'report').")

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
