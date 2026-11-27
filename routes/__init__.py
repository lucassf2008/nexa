# Pacote de rotas (blueprints) do Nexa SENAI
import os
import secrets
from flask import current_app
from werkzeug.utils import secure_filename

IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'jfif'}


def allowed_image_file(filename):
    """Verifica se o arquivo possui uma extensão de imagem permitida."""
    return bool(
        filename
        and '.' in filename
        and filename.rsplit('.', 1)[1].lower() in IMAGE_EXTENSIONS
    )


def save_uploaded_image(file_storage, prefix):
    """Valida e salva uma imagem enviada no UPLOAD_FOLDER.

    Retorna `(url_path, error_message)`:
    - `(None, None)` quando nenhum arquivo foi selecionado.
    - `(url_path, None)` quando salvo com sucesso.
    - `(None, error_message)` quando a extensão é inválida.
    """
    if not file_storage or not file_storage.filename or file_storage.filename.strip() == '':
        return None, None

    if not allowed_image_file(file_storage.filename):
        return None, 'Formato de imagem não suportado. Use PNG, JPG, JPEG, GIF, WEBP ou JFIF.'

    ext = file_storage.filename.rsplit('.', 1)[1].lower()
    stem = secure_filename(file_storage.filename.rsplit('.', 1)[0])[:40]
    token = secrets.token_hex(4)
    filename = f"{prefix}_{stem}_{token}.{ext}" if stem else f"{prefix}_{token}.{ext}"

    upload_dir = current_app.config['UPLOAD_FOLDER']
    os.makedirs(upload_dir, exist_ok=True)
    filepath = os.path.join(upload_dir, filename)
    file_storage.save(filepath)
    return f"/static/uploads/{filename}", None


def safe_form_str(form, key, fallback=None):
    """Lê um campo de formulário com fallback seguro para None."""
    if key in form:
        val = form.get(key)
        return val.strip() if val is not None else ''
    return fallback.strip() if isinstance(fallback, str) else ''
