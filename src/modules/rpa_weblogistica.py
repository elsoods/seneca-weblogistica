import re
import sys
from datetime import datetime, timedelta
from playwright.sync_api import Playwright, sync_playwright, expect
from imap_tools import MailboxLoginError
from imap_tools.mailbox import MailBox, MailBoxUnencrypted
from imap_tools.query import AND
import time
import os
from dotenv import load_dotenv
import logging

# Create a custom logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Create a handler for the terminal (StreamHandler)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)

# Create a handler for the file (FileHandler)
file_handler = logging.FileHandler("codegen.log")
file_handler.setLevel(logging.INFO)

# Define a common log format
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

# Add handlers to the logger
logger.addHandler(console_handler)
logger.addHandler(file_handler)

load_dotenv()


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


fecha_regex = re.compile(r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2} - \d{2}:\d{2}$")


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


def run(playwright: Playwright) -> None:
    try:
        browser = playwright.chromium.launch(headless=True)
        if not os.path.exists("storage_state.json"):
            context = browser.new_context()
        else:
            context = browser.new_context(storage_state="storage_state.json")
        page = context.new_page()
        page.goto("https://weblogistica.ternium.com/login")
        page.get_by_role("button", name="Ingresar con Azure").click()

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
                    ).click()
                    # Get 2FA code from email
                    code = get_2fa_code()
                    logger.info(f"2FA response: {code}")
                    page.get_by_role(
                        "textbox", name="Enter the code you received"
                    ).fill(code)
                    page.get_by_role("button", name="Sign in").click()
                    page.wait_for_load_state("load")
                    context.storage_state(path="storage_state.json")
            except Exception as e:
                login_form = page.get_by_role("textbox", name="someone@example.com")
                login_is_visible = login_form.evaluate(
                    "element => element.offsetParent !== null"
                )
                if login_is_visible:
                    page.get_by_role("textbox", name="someone@example.com").click()
                    page.get_by_role("textbox", name="someone@example.com").fill(
                        "francisco.saucedo@transportesorta.com"
                    )
                    page.get_by_role("button", name="Next").click()

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
                        ).fill(code)
                        page.get_by_role("button", name="Sign in").click()
                        page.wait_for_load_state("load")
                        context.storage_state(path="storage_state.json")
                else:
                    logger.warning("Login form is not visible. Skipping login.")
        # Handle Pop-up
        icon = page.locator(".w-3 > .fill-current")
        icon_is_visible = icon.evaluate("element => element.offsetParent !== null")
        if icon_is_visible:
            page.locator(".w-3 > .fill-current > path").click()
        page.get_by_role("listitem").filter(
            has_text="Principal Ofertas de Viajes"
        ).get_by_role("img").click()
        page.wait_for_load_state("networkidle")
        page.get_by_role("button", name="Origenes").click()
        page.get_by_role("button", name="Largos Puebla").click()
        page.get_by_text("Filtrar").click()
        logger.debug("Filtering...")
        page.wait_for_selector("div", timeout=10000)
        page.wait_for_load_state("networkidle")

        initial_count = page.locator("div").count()
        page.wait_for_function(
            f"document.querySelectorAll('div').length !== {initial_count}"
        )
        page.wait_for_load_state("networkidle")  # Ensure network activity has settled

        loop_controller = True
        while loop_controller:
            max_retries = 10
            retry_interval = 1
            posibles_fechas = None

            for trie in range(max_retries):
                posibles_fechas = page.locator("div").filter(has_text=fecha_regex)

                if posibles_fechas.count() > 0:

                    logger.debug("Dates Available")
                    oferta_texto = (
                        page.locator("div")
                        .filter(has_text=re.compile(r"^\d{8}$"))
                        .first.text_content()
                    )

                    fecha_texto = posibles_fechas.nth(0).inner_text()

                    # Use regex to safely extract components
                    match = re.match(
                        r"(\d{2}/\d{2}/\d{4}) (\d{2}:\d{2}) - (\d{2}:\d{2})",
                        fecha_texto,
                    )
                    if not match:
                        raise ValueError(f"Formato inesperado: {fecha_texto}")

                    fecha_base, hora_inicio, hora_fin = match.groups()

                    # Parse datetimes
                    dt_inicio = datetime.strptime(
                        f"{fecha_base} {hora_inicio}", "%d/%m/%Y %H:%M"
                    )
                    dt_fin = datetime.strptime(
                        f"{fecha_base} {hora_fin}", "%d/%m/%Y %H:%M"
                    )

                    # Día base
                    dia_int = int(fecha_base.split("/")[0])

                    # Si termina después de medianoche
                    if dt_fin < dt_inicio:
                        dia_int += 1
                    dia = str(dia_int)
                    logger.debug(f"Dia: {dia}")

                    logger.info("-" * 50)
                    logger.info(f"Ofert found: {oferta_texto}")
                    logger.info(f"Date found: {fecha_texto}")
                    logger.info(f"Extracted day: {dia}")
                    page.locator(".inputdate-class-position").first.click()
                    page.get_by_role("heading", name=dia, exact=True).click()

                    # Localizar y seleccionar el valor más alto del combobox de horas
                    hora_combo = (
                        page.locator("div")
                        .filter(has_text=re.compile(r"^\d{4,}$"))
                        .get_by_role("combobox")
                        .nth(0)
                    )
                    if hora_combo.count() > 0:
                        is_visible = hora_combo.evaluate(
                            "element => element.offsetParent !== null"
                        )
                        logger.info(f"Hours combo: {is_visible}")
                        if is_visible:
                            # Extraer los valores de las opciones
                            hora_values = hora_combo.evaluate_all(
                                "nodes => Array.from(nodes[0].options || []).map(o => o.value.trim()).filter(v => v)"
                            )
                            hora_values = [
                                int(value) for value in hora_values if value.isdigit()
                            ]
                            if hora_values:
                                max_hora = max(hora_values)
                                logger.info(f"Max hours: {max_hora}")
                                hora_combo.select_option(str(max_hora))
                            else:
                                logger.debug("No values available in hours combobox")
                        else:
                            logger.debug("Hours combobox not interactive")
                    else:
                        logger.debug("Hours combobox not available")
                    # Localizar y seleccionar el valor más alto del combobox de minutos
                    try:
                        minuto_combo = (
                            page.locator("div")
                            .filter(has_text=re.compile(r"^\d{4,}$"))
                            .get_by_role("combobox")
                            .nth(1)
                        )
                        if minuto_combo.count() > 0:
                            is_visible = minuto_combo.evaluate(
                                "element => element.offsetParent !== null"
                            )
                            logger.info(f"Minutes combobox: {is_visible}")
                            if is_visible:
                                minuto_values = minuto_combo.evaluate_all(
                                    "nodes => Array.from(nodes[0].options || []).map(o => o.value.trim()).filter(v => v)"
                                )
                                minuto_values = [
                                    int(value)
                                    for value in minuto_values
                                    if value.isdigit()
                                ]
                                if minuto_values:
                                    max_minuto = max(minuto_values)
                                    logger.info(f"Max Minutes: {max_minuto}")
                                    minuto_combo.select_option(str(max_minuto))
                                else:
                                    logger.debug(
                                        "No values available in minutes combobox"
                                    )
                            else:
                                logger.debug("Minutes combo not interactive")
                        else:
                            logger.debug("Minutes combo not available")
                    except Exception as e:
                        logger.debug("No minutes found, continuing...")

                    time.sleep(1)
                    page.get_by_text("Aceptar").click()
                    page.get_by_text("Confirmar").click()
                    # page.wait_for_selector("div:has-text('ACEPTAR')", timeout=10000)  # Waits for up to 10 seconds
                    time.sleep(2)
                    page.get_by_text("ACEPTAR").click()
                    time.sleep(5)
                    page.get_by_text("ACEPTAR").click()
                    logger.info("Confirmed Offer...")
                    # input("Press enter to close browser...")
                    # break
                    page.get_by_text("Filtrar").click()
                    logger.info("Finished flow")
                    logger.info("-" * 50)
                    # page.get_by_text("Cancelar").click()
                if trie == 1:
                    logger.debug("Waiting for data")
                time.sleep(retry_interval)
            else:
                logger.debug("No dates available")
                page.get_by_text("Filtrar").click()
                logger.debug("Running filter again...")

                # time.sleep(10)
                # page.get_by_text("Filtrar").click()
                # page.get_by_role("button", name="__/__/____").click()
            # page.locator("div").filter(has_text=re.compile(r"^07/05\/2025 15:00 - 23:00$")).first.click()
            # page.locator(".inputdate-class-position").first.click()
            # page.get_by_role("heading", name="7", exact=True).click()
            # page.locator("div").filter(has_text=re.compile(r"^2122$")).get_by_role("combobox").select_option("22")
            # page.locator("div").filter(has_text=re.compile(r"^00153045$")).get_by_role("combobox").select_option("45")
            # page.get_by_text("/05/2025 15:00 - 23:00").click()

            # ---------------------
        context.close()
        browser.close()
    except Exception as e:
        print(f"Error: {e}")
        if "browser" in locals():
            browser.close()
        if "context" in locals():
            context.close()


def test_run():
    with sync_playwright() as playwright:
        run(playwright)
