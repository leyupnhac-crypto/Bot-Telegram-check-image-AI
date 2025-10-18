import os
import logging
import requests
from flask import Flask, request
from telegram import Bot, Update, BotCommand
from telegram.ext import Dispatcher, MessageHandler, Filters, CommandHandler, CallbackContext

# --- LẤY TỪ BIẾN MÔI TRƯỜNG CỦA RENDER ---
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')

# === THAY ĐỔI QUAN TRỌNG: LẤY DANH SÁCH KEY ===
# 1. Lấy chuỗi key (phân tách bằng dấu phẩy) từ biến môi trường
API_KEYS_STRING = os.environ.get('AIORNOT_API_KEYS', '') # Lấy key CÓ CHỮ S

# 2. Tách chuỗi thành một danh sách (list), loại bỏ khoảng trắng thừa
AIORNOT_KEYS_LIST = [key.strip() for key in API_KEYS_STRING.split(',') if key.strip()]

# 3. Biến đếm toàn cục để xoay vòng key
key_index_counter = 0
# === KẾT THÚC THAY ĐỔI ===

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

# === THAY ĐỔI: Hàm này giờ nhận 'api_key' làm tham số ===
def check_image_with_aiornot(image_data: bytes, api_key: str) -> dict:
    """Tải DỮ LIỆU ảnh lên AIorNot v2 (dùng key được cung cấp)."""
    
    api_url = 'https://api.aiornot.com/v2/image/sync'
    
    headers = {
        'Authorization': f"Bearer {api_key}", # Dùng key được đưa vào
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
    
    # === THAY ĐỔI: Logic chọn Key ===
    global key_index_counter # Gọi biến đếm toàn cục
    
    # 1. Kiểm tra xem có key nào không
    if not AIORNOT_KEYS_LIST:
        logger.error("!!! LỖI NGHIÊM TRỌNG: Không tìm thấy API key nào. Vui lòng kiểm tra biến 'AIORNOT_API_KEYS' trên Render.")
        update.message.reply_text("Lỗi: Bot chưa được cấu hình API key. Vui lòng liên hệ chủ bot.")
        return

    # 2. Chọn key theo kiểu xoay vòng
    # (key_index_counter % len(AIORNOT_KEYS_LIST)) sẽ cho ra 0, 1, 2, 0, 1, 2...
    current_key = AIORNOT_KEYS_LIST[key_index_counter % len(AIORNOT_KEYS_LIST)]
    
    # 3. Tăng biến đếm để lần sau dùng key tiếp theo
    key_index_counter += 1
    
    # Ghi log (Màu vàng) để bạn biết bot đang dùng key nào (chỉ hiện index)
    logger.warning(f"Đang sử dụng Key Index: {key_index_counter % len(AIORNOT_KEYS_LIST)} / Tổng số: {len(AIORNOT_KEYS_LIST)}")
    # === KẾT THÚC THAY ĐỔI ===

    try:
        photo_file = update.message.photo[-1].get_file()
        image_bytes = photo_file.download_as_bytearray()

        waiting_message = update.message.reply_text(f"Đang phân tích ảnh (dùng key #{key_index_counter % len(AIORNOT_KEYS_LIST)})...")
        
        # 4. Gửi key đã chọn vào hàm check
        result = check_image_with_aiornot(image_bytes, current_key)
        
        context.bot.delete_message(chat_id=waiting_message.chat_id, message_id=waiting_message.message_id)

        if not result:
            update.message.reply_text("Có lỗi xảy ra trong quá trình phân tích (API error / Timeout).")
            return

        logger.warning(f"ĐÃ NHẬN PHẢN HỒI TỪ API: {result}")

        report = result.get('report')

        if report:
            # Logic đọc kết quả (đã sửa đúng theo log của bạn)
            ai_info = report.get('ai_generated', {})
            verdict = ai_info.get('verdict', 'N/A')
            ai_score_percent = ai_info.get('ai', {}).get('confidence', 0) * 100

            generator_info = report.get('generator', {})
            generator_name = "Không rõ"
            if generator_info:
                try:
                    generator_name = max(generator_info.items(), key=lambda item: item[1].get('confidence', 0))[0]
                    generator_name = generator_name.replace("_", " ").title()
                except ValueError:
                    generator_name = "Không rõ"

            deepfake_detected = report.get('deepfake', {}).get('is_detected', None)
            deepfake_verdict = "Phát hiện" if deepfake_detected else "Không"

            nsfw_detected = report.get('nsfw', {}).get('is_detected', None)
            nsfw_verdict = "Phát hiện" if nsfw_detected else "Không"

            quality_detected = report.get('quality', {}).get('is_detected', None)
            quality_verdict = "Tốt" if quality_detected else "Thấp"
            
            response_text = ""
            if verdict == 'ai':
                response_text = f"Kết quả: **Ảnh này là do AI tạo ra** 🤖\n"
                response_text += f"Điểm AI tổng quát: **{ai_score_percent:.1f}%**\n"
                response_text += f"Nguồn AI (Ước tính): **{generator_name}**\n"
            elif verdict == 'human' or verdict == 'clear':
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
        
    # Kiểm tra xem có key nào không trước khi set webhook
    if not AIORNOT_KEYS_LIST:
        logger.error("!!! LỖI: Không tìm thấy key nào trong 'AIORNOT_API_KEYS'. Bot sẽ không hoạt động.")
        return

    logger.info(f"Đã tải thành công {len(AIORNOT_KEYS_LIST)} API key.")

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
