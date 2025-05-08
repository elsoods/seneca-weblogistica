# Automatización de Weblogística - Ternium/Orta

Automatización diseñada para revisar y gestionar el sitio web de asignación de embarques Weblogistica y agiliza la obtencion de pedidos. Esta herramienta está destinada a ejecutarse como un servicio en una máquina virtual Linux.

## Requisitos

- **Python**: Versión 3.8 o superior.
- **Sistema Operativo**: Linux

## Instalación

### 1. Instalación de dependencias

Ejecute el siguiente comando para instalar las dependencias necesarias:

```bash
pip install -r requirements.txt
```

### 2. Instalación de ChromeDriver y Playwright

Instale ChromeDriver y las dependencias de Playwright con el siguiente comando:

```bash
playwright install --with-deps
```

### 3. Configuración del servicio

Cree un archivo de configuración para el servicio en `/etc/systemd/system/weblogistica.service` con el siguiente contenido:

```ini
[Unit]
Description=Servicio de Automatización Weblogística
After=network.target

[Service]
ExecStart=/usr/bin/python3 /ruta/a/src/main.py
WorkingDirectory=/ruta/a/
Restart=always
User=usuario
Group=grupo

[Install]
WantedBy=multi-user.target
```

Recuerde reemplazar `/ruta/a/` con la ruta donde se encuentra el proyecto y ajustar `usuario` y `grupo` según su configuración.

Habilite y arranque el servicio:

```bash
sudo systemctl enable weblogistica.service
sudo systemctl start weblogistica.service
```

## Ejecución Manual

Si desea ejecutar la herramienta manualmente, utilice el siguiente comando:

```bash
python src/main.py
```
