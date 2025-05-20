import re
import sys
from playwright.sync_api import Playwright, sync_playwright, expect
from imap_tools import MailboxLoginError
from imap_tools.mailbox import MailBox, MailBoxUnencrypted
from imap_tools.query import AND
from dataclasses import dataclass
import time
import os
from dotenv import load_dotenv
import logging
import sqlite3
from logging.handlers import TimedRotatingFileHandler
import json
import pytz
from datetime import datetime


# Get the directory of the current file (e.g., modules/)
current_dir = os.path.dirname(os.path.abspath(__file__))

# Go one level up (e.g., project root)
base_dir = os.path.abspath(os.path.join(current_dir, os.pardir, os.pardir))

# Create a custom logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Create a handler for the terminal (StreamHandler)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)

# Create a handler for the file (FileHandler)
log_dir = os.path.join(base_dir, "log")
os.makedirs(log_dir, exist_ok=True)

file_handler = TimedRotatingFileHandler(
    os.path.join(log_dir, "weblogistica_run"), when="midnight", interval=1, backupCount=7, encoding="utf-8"
)
file_handler.suffix = "-%Y-%m-%d.log"
file_handler.setLevel(logging.INFO)

# Define a common log format
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

# Add handlers to the logger
logger.addHandler(console_handler)
logger.addHandler(file_handler)

load_dotenv()



@dataclass
class Dia:
    dia: str
    added: bool

@dataclass
class OfferData:
    offer_id: str
    fecha: str
    dia: str
    hora_inicio: str
    hora_fin: str
    hora_seleccionada: str | None
    hora_combo: list | None
    minuto_combo: list | None
    origen: str = "Largos Puebla"


def extract_2fa_code(text: str) -> str | None:
    """
    Extrae un número de 6 a 8 dígitos del texto (tu código es de 8).
    """
    match = re.search(r"\b\d{6,8}\b", text)
    return match.group() if match else None


def get_2fa_code() -> str:
    try:
        with MailBoxUnencrypted(os.getenv("EMAIL_HOST", ""), port=143).login(
            os.getenv("EMAIL_USER", ""),
            os.getenv("EMAIL_PASS", ""),
            initial_folder="INBOX",
        ) as mailbox:
            logger.debug("logged in")
            timeout = time.time() + 120
            subject_filter = "Your Ternium account verification code"
            while time.time() < timeout:
                for msg in mailbox.fetch(
                    AND(seen=False, subject=subject_filter), reverse=True
                ):
                    code = extract_2fa_code(msg.text or msg.html or "")
                    if code:
                        return code
                time.sleep(3)
            raise TimeoutError("No se recibió el código 2FA a tiempo.")
    except MailboxLoginError as e:
        return f"Error de inicio de sesión: {e}"
    except Exception as e:
        return f"Error al obtener el código 2FA: {e}"


fecha_regex = re.compile(r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}(?: - \d{2}:\d{2})?$")


def select_max_in_combobox(combo):
    # Esperar a que el combobox esté disponible
    try:
        combo.wait_for(
            timeout=5000
        )  # Esperar hasta 5 segundos para que el combobox esté disponible
    except Exception:
        raise ValueError("El combobox no está disponible o no tiene opciones visibles.")

    # Obtener todas las opciones dentro del combobox
    options = combo.locator("div").all()
    print(
        f"Opciones encontradas: {[opt.inner_text() for opt in options]}"
    )  # Depuración

    # Verificar si hay opciones disponibles
    if not options:
        raise ValueError("El combobox no tiene opciones disponibles.")

    # Extraer los valores y convertirlos a enteros
    values = []
    for opt in options:
        text = opt.inner_text().strip()
        if text.isdigit():  # Verificar si el texto es un número
            values.append(int(text))

    # Verificar si hay valores válidos
    if not values:
        raise ValueError("No se encontraron valores numéricos en el combobox.")

    # Seleccionar el valor máximo
    max_value = max(values)
    print(f"Seleccionando el valor máximo: {max_value}")  # Depuración
    combo.select_option(str(max_value))


def select_max_combobox_option(combo, label="") -> tuple[bool, str | None, list | None]:
    try:
        # Esperar a que esté en el DOM y sea visible
        combo.wait_for(state="attached", timeout=5000)
        combo.wait_for(state="visible", timeout=5000)

        is_visible = combo.evaluate("el => el.offsetParent !== null")
        logger.info(f"{label} combo visible: {is_visible}")
        if not is_visible:
            return False, None, None

        # Obtener todas las opciones
        values = combo.evaluate(
            """
            el => Array.from(el.options || []).map(o => ({
                value: o.value.trim(),
                disabled: o.disabled
            }))
        """
        )
        logger.debug(f"{label} options: {values}")

        valid_values = [
            int(v["value"])
            for v in values
            if v["value"].isdigit() and not v["disabled"]
        ]

        if valid_values:
            max_value = max(valid_values)
            logger.info(f"{label} max value: {max_value}")
            exact_option = next(
                (v["value"] for v in values if int(v["value"]) == max_value),
                str(max_value),
            )
            combo.select_option(exact_option)
            return True, exact_option, valid_values
        else:
            logger.warning(f"{label} combobox has no enabled numeric options.")
            return False, None, None

    except Exception as e:
        logger.exception(f"Error selecting from {label} combo: {e}")
        return False, None, None


def run(playwright: Playwright) -> None:
    try:
        browser = playwright.chromium.launch(headless=False)
        # if not os.path.exists("storage_state.json"):
        if not os.path.exists(os.path.join(base_dir, "storage_state.json")):
            logger.debug("storage_state doesnt exists")
            context = browser.new_context(
                record_video_dir=os.path.join(base_dir, "recordings")
            )
        else:
            context = browser.new_context(
                storage_state=os.path.join(base_dir, "storage_state.json"),
                record_video_dir=os.path.join(base_dir, "recordings"),
            )
        page = context.new_page()
        page.goto(
            "https://weblogistica.ternium.com/login", wait_until="load", timeout=20000
        )
        # page.wait_for_selector('button:has-text("Ingresar con Azure")', timeout=10000)
        page.wait_for_selector(
            'button:has-text("Ingresar con Azure")', state="visible", timeout=15000
        )
        # page.wait_for_selector(".modal-overlay", state="detached", timeout=15000)
        page.get_by_role("button", name="Ingresar con Azure").click(timeout=10000)
        # Wait for the login-callback URL or proceed with login
        try:
            page.wait_for_url("**/login-callback**", timeout=5000)
            logger.debug("Navigated to login callback. Continuing process.")
        except Exception as e:
            logger.info(
                "Did not navigate to login callback immediately. Proceeding with login."
            )
            try:
                page.locator(
                    '[data-test-id="francisco\\.saucedo\\@transportesorta\\.com"]'
                ).wait_for(state="visible", timeout=10000)
                page.locator(
                    '[data-test-id="francisco\\.saucedo\\@transportesorta\\.com"]'
                ).click()
                try:
                    page.wait_for_url("**/login-callback**", timeout=5000)
                    logger.debug(
                        "Navigated to login callback after entering email. Continuing process."
                    )
                except Exception as e:
                    logger.info(
                        "Did not navigate to login callback after email. Proceeding with 2FA."
                    )
                    page.get_by_role(
                        "textbox", name="Enter the code you received"
                    ).wait_for(state="visible", timeout=10000)
                    page.get_by_role(
                        "textbox", name="Enter the code you received"
                    ).click()
                    # Get 2FA code from email
                    code = get_2fa_code()
                    logger.info(f"2FA response: {code}")
                    page.get_by_role(
                        "textbox", name="Enter the code you received"
                    ).fill(code)
                    page.get_by_role("button", name="Sign in").wait_for(
                        state="visible", timeout=10000
                    )
                    page.get_by_role("button", name="Sign in").click()
                    page.wait_for_load_state("load")
                    context.storage_state(path="storage_state.json")
            except Exception as e:
                login_form = page.get_by_role("textbox", name="someone@example.com")
                login_is_visible = login_form.evaluate(
                    "element => element.offsetParent !== null"
                )
                if login_is_visible:
                    page.get_by_role("textbox", name="someone@example.com").wait_for(
                        state="visible", timeout=10000
                    )
                    page.get_by_role("textbox", name="someone@example.com").click()
                    page.get_by_role("textbox", name="someone@example.com").fill(
                        "francisco.saucedo@transportesorta.com"
                    )
                    page.get_by_role("button", name="Next").wait_for(
                        state="visible", timeout=10000
                    )
                    page.get_by_role("button", name="Next").click(timeout=10000)

                    # Wait for the callback URL again after entering email
                    try:
                        page.wait_for_url("**/login-callback**", timeout=5000)
                        logger.debug(
                            "Navigated to login callback after entering email. Continuing process."
                        )
                    except Exception as e:
                        logger.info(
                            "Did not navigate to login callback after email. Proceeding with 2FA."
                        )
                        # page.get_by_role(
                        #     "textbox", name="Enter the code you received"
                        # ).click()
                        # Get 2FA code from email
                        code = get_2fa_code()
                        logger.debug(code)
                        page.get_by_role(
                            "textbox", name="Enter the code you received"
                        ).wait_for(state="visible", timeout=10000)
                        page.get_by_role(
                            "textbox", name="Enter the code you received"
                        ).fill(code)
                        page.get_by_role("button", name="Sign in").wait_for(
                            state="visible", timeout=10000
                        )
                        page.get_by_role("button", name="Sign in").click(timeout=10000)
                        page.wait_for_load_state("load")
                        context.storage_state(
                            path=os.path.join(base_dir, "storage_state.json")
                        )
                else:
                    logger.warning("Login form is not visible. Skipping login.")
        # Handle Pop-up
        icon_locator = page.locator(".w-3 > .fill-current")
        try:
            icon_locator.wait_for(state="visible", timeout=30000)
            if icon_locator.count() > 0:
                icon_is_visible = icon_locator.evaluate(
                    "element => element.offsetParent !== null"
                )
                if icon_is_visible:
                    icon_locator.click(timeout=5000)
        except Exception as e:
            logger.debug(f"No popup found | {e}")
        # Wait for any modal overlays to disappear before clicking
        # page.wait_for_selector(".modal-overlay", state="detached", timeout=15000)
        # page.evaluate(
        #     "document.querySelectorAll('.modal-overlay').forEach(e => e.remove())"
        # )
        listitem_img = (
            page.get_by_role("listitem")
            .filter(has_text="Principal Ofertas de Viajes")
            .get_by_role("img")
        )
        listitem_img.wait_for(state="visible", timeout=10000)
        listitem_img.click(timeout=10000)
        page.wait_for_load_state("networkidle")

        origenes_btn = page.get_by_role("button", name="Origenes")
        origenes_btn.wait_for(state="visible")
        origenes_btn.click()

        largos_btn = page.get_by_role("button", name="Largos Puebla")
        largos_btn.wait_for(state="visible", timeout=10000)
        largos_btn.click()

        filtrar_btn = page.get_by_text("Filtrar")
        filtrar_btn.wait_for(state="visible", timeout=10000)
        filtrar_btn.click()
        logger.debug("Filtering...")

        page.wait_for_selector("div", timeout=10000)
        page.wait_for_load_state("networkidle")

        initial_count = page.locator("div").count()
        page.wait_for_function(
            f"document.querySelectorAll('div').length !== {initial_count}"
        )
        # page.wait_for_load_state("networkidle")  # Ensure network activity has settled

        loop_controller = True
        while loop_controller:
            max_retries = 10
            retry_interval = 1

            for trie in range(max_retries):
                # Localizar todos los bloques que contengan oferta y fecha dentro
                page.wait_for_selector(
                    ".modal-overlay", state="detached", timeout=15000
                )
                page.evaluate(
                    """() => {
                    // Force browser to recalculate layout and repaint
                    document.body.style.zoom = "99%";
                    setTimeout(() => { document.body.style.zoom = "100%"; }, 10);
                }"""
                )
                page.wait_for_load_state("networkidle")
                page.wait_for_selector("div", timeout=7000)
                bloques = page.locator('div.flex.font-medium.text-11px.xl\\:text-13px.w-2\\/3')
                total_bloques = bloques.count()
                if trie == 0:
                    logger.debug(f"Total bloques encontrados: {total_bloques}")

                for i in range(total_bloques):
                    bloque = bloques.nth(i)
                    columnas = bloque.locator('> div')
                    # print(columnas)

                    # Extraer el ID de la oferta
                    try:
                        oferta_texto = columnas.nth(0).locator('span').inner_text()
                        # logger.debug(f"Found offer ID: {oferta_texto}")
                        fecha_texto = columnas.nth(2).locator('span').inner_text()
                        # logger.info(f"Oferta: {oferta_texto}, Fecha: {fecha_texto}")
                        match = re.match(fecha_regex, fecha_texto)
                        if not match:
                            logger.warning(
                                f"Formato inesperado en fecha: '{fecha_texto}'"
                            )
                            continue  # pasa al siguiente bloque si la fecha está mal formada

                        logger.info("-" * 50)
                        input_button = bloque.locator(".inputdate-class-position")
                        if input_button.count() > 0:
                            input_button.first.wait_for(
                                state="visible", timeout=10000
                            )
                            input_button.first.click()
                        else:
                            logger.warning(
                                "No se encontró inputdate en el bloque correspondiente"
                            )

                        parts = fecha_texto.split(" ")
                        fecha = parts[0]
                        hora_inicio = parts[1]

                        # Handle both single time and time range formats
                        if " - " in fecha_texto:
                            hora_fin = parts[3]
                            dia_obj = Dia(
                                (
                                    str(int(fecha.split("/")[0]))
                                    if hora_fin < hora_inicio
                                    else str(int(fecha.split("/")[0]))
                                ),
                                hora_fin
                                < hora_inicio,  # Added day if end time < start time
                            )
                        else:
                            # For single time format, no day adjustment needed
                            dia_obj = Dia(str(int(fecha.split("/")[0])), False)
                            hora_fin = hora_inicio
                        if hora_fin < hora_inicio:
                            dia_obj = Dia(
                                str(int(fecha_texto.split("/")[0]) + 1), True
                            )
                        else:
                            dia_obj = Dia(
                                str(int(fecha_texto.split("/")[0])), False
                            )

                        heading = page.get_by_role(
                            "heading", name=dia_obj.dia, exact=True
                        )
                        parent_class = heading.evaluate("el => el.parentElement.className")
                        # logger.debug(f"Day {dia_obj.dia} parent class: {parent_class}")
                        if "cursor-pointer" in parent_class:
                            heading.click()
                        else:
                            logger.info(f"Day {dia_obj.dia} is not clickable (parent class: {parent_class}). Trying one day before.")
                            if dia_obj.added:
                                dia_alt = str(int(dia_obj.dia) - 1)
                                dia_obj.dia = dia_alt
                                heading_alt = page.get_by_role("heading", name=dia_alt, exact=True)
                                heading_alt.wait_for(state="visible", timeout=10000)
                                parent_class_alt = heading_alt.evaluate("el => el.parentElement.className")
                                if "cursor-pointer" in parent_class_alt:
                                    heading_alt.click()
                                else:
                                    logger.info(f"Day {dia_alt} is also not clickable. Skipping offer...")
                                    continue
                            else:
                                logger.info("Can't select day. Skipping offer...")
                                continue

                        logger.info(f"Ofert found: {oferta_texto}")
                        logger.info(f"Date found: {fecha_texto}")
                        logger.info(f"Extracted day: {dia_obj.dia}")

                        hora_combo = page.get_by_role("combobox").nth(0)
                        hora_combo.wait_for(state="visible", timeout=10000)
                        success, selected_hour, hora_combo_val = select_max_combobox_option(hora_combo, label="Hora")

                        minuto_combo = page.get_by_role("combobox").nth(1)
                        minuto_combo.wait_for(state="visible", timeout=10000)
                        # select_max_combobox_option(minuto_combo, label="Minuto")
                        success, selected_minute, minuto_combo_val = select_max_combobox_option(minuto_combo, label="Hora")

                        diaobj = OfferData(
                            oferta_texto, 
                            fecha_texto,
                            dia_obj.dia, 
                            hora_inicio, 
                            hora_fin, 
                            f"{selected_hour}:{selected_minute}",
                            hora_combo_val,
                        minuto_combo_val
                        )

                        insert_offer_to_db(diaobj)

                        aceptar_btn = page.get_by_text("Aceptar", exact=True)
                        # aceptar_btn.wait_for(state="visible")
                        aceptar_btn.click()
                    except Exception as e:
                        logger.warning(f"Error al procesar bloque {i}: {e}")
                        continue
                if total_bloques > 0:
                    try:
                        time.sleep(1)
                        confirmar_btn = page.get_by_text("Confirmar")
                        confirmar_btn.wait_for(state="visible", timeout=5000)
                        confirmar_btn.click()

                        # Wait for the confirmation modal to appear (adjust selector as needed)
                        page.wait_for_selector('text=ACEPTAR', state='visible', timeout=5000)

                        # Click the "ACEPTAR" button in the confirmation modal
                        aceptar_btn = page.get_by_text("ACEPTAR", exact=True)
                        aceptar_btn.wait_for(state="visible", timeout=5000)
                        aceptar_btn.click()
                        time.sleep(2)
                        # Wait for the modal to appear (adjust selector if needed)
                        modal = page.locator(".modal-producto-content")
                        modal.wait_for(state="visible", timeout=15000)


                        # Wait for the confirmation modal to appear (adjust selector as needed)
                        page.wait_for_selector('text=ACEPTAR', state='visible', timeout=5000)

                        # Click the "ACEPTAR" button in the confirmation modal
                        aceptar_btn2 = page.get_by_text("ACEPTAR", exact=True)
                        aceptar_btn2.wait_for(state="visible", timeout=5000)
                        aceptar_btn2.click()
                        # time.sleep(5)
                        # Wait for the modal to appear (adjust selector if needed)
                        # modal = page.locator(".modal-producto-content")
                        # modal.wait_for(state="visible", timeout=15000)

#                         aceptar_final_btn = modal.locator("div.cursor-pointer:has(span:text('ACEPTAR'))")
#                         aceptar_final_btn.wait_for(state="attached", timeout=10000)
#                         aceptar_final_btn.wait_for(state="visible", timeout=10000)
#                         # aceptar_final_btn.wait_for(state="enabled", timeout=10000)
#                         page.wait_for_function("el => !el.hasAttribute('disabled')", arg=aceptar_final_btn)
#                         aceptar_final_btn.evaluate("el => el.scrollIntoView({block: 'center'})")
#
# # Retry clicking and waiting for modal to close
#                         max_retries_aceptar = 3
#                         for attempt in range(max_retries_aceptar):
#                             try:
#                                 aceptar_final_btn.evaluate("el => el.click()")
#                                 logger.info(f"Clicked final ACEPTAR button (attempt {attempt + 1}).")
#                                 # Wait for overlay to disappear as a result of the click
#                                 page.wait_for_selector(".modal-overlay", state="detached", timeout=10000)
#                                 logger.info("Confirmed Offer (modal closed).")
#                                 break
#                             except Exception as e:
#                                 logger.warning("Modal did not close, retrying ACEPTAR click...")
#                                 if attempt == max_retries_aceptar - 1:
#                                     page.screenshot(path=f"modal_not_closed_{int(time.time())}.png")
#                                     logger.error("Modal did not close after retries. Screenshot taken.")
#                                     raise
#
#                         # Ensure modal overlay is gone before proceeding
#                         try:
#                             page.wait_for_selector(".modal-overlay", state="detached", timeout=20000)
#                             logger.info("Modal overlay detached, continuing.")
#                         except Exception:
#                             page.screenshot(path=f"overlay_not_gone_{int(time.time())}.png")
#                             logger.error("Modal overlay did not detach after retries. Screenshot taken.")
#                             raise
                    except Exception as e:
                        logger.error(
                            f"Failed to click final ACEPTAR button: {e}"
                        )
                    try:
                        logger.debug(
                            "Waiting for 'Filtrar' to be available again..."
                        )
                        page.get_by_text("Filtrar", exact=True).wait_for(
                            state="visible", timeout=5000
                        )
                        page.get_by_text("Filtrar", exact=True).click()
                        logger.info("Finished flow, refreshing filter...")
                    except Exception as e:
                        logger.exception("Could not click 'Filtrar'")

                # if total_bloques > 0:
                #     input("Press enter to close browser...")
                #     break

                if trie == 0:
                    logger.debug("Waiting for data")
                time.sleep(retry_interval)
            else:
                logger.debug("No dates available")
                filtrar_btn = page.get_by_text("Filtrar")
                filtrar_btn.wait_for(state="visible", timeout=10000)
                filtrar_btn.click()
                logger.debug("Running filter again...")

        context.close()
        browser.close()
    except Exception as e:
        print(f"Error: {e}")
        if "browser" in locals():
            browser.close()
        if "context" in locals():
            context.close()


def insert_offer_to_db(diaobj: OfferData) -> None:
    def get_mexico_time():
        tz = pytz.timezone("America/Mexico_City")
        return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

    db_dir = os.path.join(base_dir, "src", "db")
    os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(os.path.join(db_dir, "offers.db"))
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            offer_id TEXT,
            origen TEXT,
            fecha TEXT,
            dia TEXT,
            hora_inicio TEXT,
            hora_fin TEXT,
            hora_seleccionada TEXT,
            hora_combo TEXT,
            minuto_combo TEXT,
            processed_at TEXT
        )
    """)
    c.execute(
        "INSERT INTO offers (offer_id, origen, fecha, dia, hora_inicio, hora_fin, hora_seleccionada, hora_combo, minuto_combo, processed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (diaobj.offer_id, diaobj.origen, diaobj.fecha, diaobj.dia, diaobj.hora_inicio, diaobj.hora_fin, diaobj.hora_seleccionada, json.dumps(diaobj.hora_combo), json.dumps(diaobj.minuto_combo), get_mexico_time()),
    )
    conn.commit()
    conn.close()


def test_run():
    with sync_playwright() as playwright:
        run(playwright)
