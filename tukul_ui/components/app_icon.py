"""Icono de ventana de Tukul, embebido como PNG.

El icono del gestor de ventanas (la barra de tareas, el alt-tab) ayuda a
reconocer la aplicación entre las demás ventanas abiertas. Se usa el isotipo
compacto —círculo de piedra nocturna, alas jade y lomo blanco—, el mismo dibujo
que `tukul_ui/components/top_bar.py` pinta en la cabecera y que corresponde a
`docs/assets/tukul-isotipo.svg`.

El PNG viaja **dentro del módulo** en base64, no como archivo suelto, por una
razón concreta de empaquetado: el release se construye con
`pyinstaller --onefile --name tukul tukul.py` **sin `--add-data`**, así que
ningún asset externo entra en el binario. Un `docs/assets/tukul-isotipo.svg`
leído en tiempo de ejecución funcionaría con `pip install -e .` pero la ventana
del binario distribuido saldría sin icono. Embeberlo elimina esa dependencia de
ruta (y de `sys._MEIPASS`) y hace que el icono sea igual en las dos formas de
instalar.

`tk.PhotoImage(data=...)` acepta el base64 de un PNG directamente y devuelve una
imagen válida sin depender de Pillow. La imagen tiene fondo transparente, de modo
que el gestor de ventanas la componga sobre el color que corresponda.
"""
from __future__ import annotations

import base64
import tkinter as tk

#: PNG RGBA de 64x64 con el isotipo transparente, en base64. 64 px es el tamaño
#: que el gestor de ventanas reescala con más fidelidad: por debajo, el lomo
#: blanco y el borde del círculo se emborronan.
_ICONO_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAMWUlEQVR4nORbaWwV1xU+s7zF9pvn"
    "5XlhTSyFQIJt1hoX0VYOi83SiIgqipS2Uqu2kdqmlaJKVCgKgqZtKrpKJeqPtFJSiVZV/qRVApgE"
    "6qQlCMySYnBIQlonMhBsMBhv7812e841M+/Oe377OCDls8Zv7p27nHPmnHPvPfeODJ9xqHAHsGRJ"
    "R0UiDPWKLdVR2pLZUCgOg2fPHhqHTxkSzDCaV3VukSTYircrGIM6SeJMl2UoPskYG0KyBrHOabDs"
    "V3pPHjoAMwjfBbCgbVM0xNgWCdgjIEmbsAMNSgAK7RZSuR9s+xV7XH+tr697DHyEbwLgjAPbITP4"
    "IbZaDjMBxsYZwO/ikrzn4vEDt8AH+CKAllUbn8KWnsHb6kxlDD0BlqWDbdn4Mk2wTBN/Lf5MlhVQ"
    "VBV/8VJkUJQABILhjP0xYMP4/7mxq/re/v7uOJSAEgTwqNLSNvItJH8nJuamPrVtBkZiAuLxcUjg"
    "xW4zmzdhKJRQuALC4QgEQmEUjpxeiMEAasSucye0FwFeLqwDpx8oAovWrNECpvYPrNye+swyDRgb"
    "vQGJiVF6U+AHJPwLlUUgEq1BTQmkF2BwWIrbW4sZRQoWwMKV7bUhJdSNDq5JzLcsEyZGb8LE+E2Y"
    "SZRXVEK5Vo1mkjKCMzhjKWx937GuYSgABQlg8cr198iq+hZWutfJIzueGBuBcXzr4NMbzwlJhopI"
    "FV6V3FQcoMZdtHRl/btn9n+Ud1P5Flzc2tmE/ukIVql38siRDV8bQMdmwp0AOcvq2jkes8B5xBV0"
    "Pxv6errO59NGXgJoblvXACzwDk5OZjl5ZOvD1y7dMeYdyGgKNbVzpxGCsqKvZ/8nOevnKrB48eIg"
    "QOCQyLxp6HB9aOCOM08gGoaRFtPU3Tycbc6WJevAFO3ZkVMAsjb/L6gmS5y0aRhc7Qsd1mYS5IeG"
    "BwfAMjxCWCZr97yUq66S7WHzqo27sKHvJjuy4Qap/V3EfBIMEjjvCJdHiXmeg/+b6+YssIYuX3wr"
    "U62MPmBx64ZliqyccZvHSTkxb+glTbxmHMFQGVTF5rhCQLJxTsaWZHKKGU1AkZQ/iOnRkSHfmVdx"
    "+kuXn9ATk0jrNTeNcqBJ5O8zlZ9WAM2tG7ehbnxebHRy3Je1hweVlZX88huT4yOcZgc4k3yoqbXj"
    "4enKpgugvR1XJPAbJ0mqf+vmIL+36zVgkRD4BU3T+OUXiDaikUA0E+0OZEn+FUzDb1pGy0T4B+JM"
    "b3LiFh/zCfaXFoD+04fBamsEP6BFNH75AaKJaCMaeRppJtpdSLCwZVXn91LreQTQuKy9ilZXTpqh"
    "1x+7dd19zprRuWhlYD3xRTCeWgssVgGlIBKN8KsUEA1EC9FEtBGNDoh24sEtK8FuWsiJ9T0C0IKh"
    "r6HTiLoNjA67DbDyANjzkst91jwXjGdRG9Y9UPQKIFYT41cxoD6pb6KBaHFANBKtvAzSPj52w32G"
    "vqAmaGiPi+3I3kalDvce7Ud0fHZzcmhxEQqA9XgrmNs7XNsrBLFYLb8KBfVFfVLfRIMIopEtanDT"
    "tFATfQGTWIdYXhSAjFXXOgkDvShjgvo0p8U8ks+wQ2P3l8Hc3ARMyTm5dKGh+msFmAC1TX1QXyKT"
    "qbAEWokHikY5kBh0imVdaltaO76A4nONmmZVIuwsHfKGgyrYX1kBxs7NYDfWQD4oxAlSm7xt7IP6"
    "ygbRDxD0hBAnQR4xhLfaSboCYJLkUY1EPCkA7uxq83xTaIPG05vAeOxzwHIQms8wSG1QW9QmzKuG"
    "vIC0ig6aQnKeNgFcXkUKlzo3tmXhMJJcWNgpEs0FCaderONBMFbMB+WPR0H5YHDacrnevnV/PVjf"
    "XsMZKjR0ZT/QAMrR//J7Wr0ST7LiLH3YMqecqwHoO2Y794bhnfLaWew/K5Bw88cdYHy9DVhZeiwv"
    "0zBIZakO1c1b81KQSrPIE44G7tJe1ABXACQtlxi6FtVDseBeuX0hGEvngbrvOMhnBtxnNATquu4l"
    "fPk8ML/ahgH28pJi9qxpNqfdacPDk/CyXQHgSDHbGeUobu/mk91V+DD9RYbMJx8C6fTHoL5wFCTd"
    "5EOgfttDk62b31kDbMU94AuQZqJdGpiaB4hLeIkx16a5CeBmZb0kDPKitCAa9symSgUxyO6rxWVr"
    "EEJ4kROke8rzjXmYmgRBRTIg5IlhSFKgpWUL96hcAFZYmi1Wpt0bB3LfFVD3HAIY9m/jls2t8jhA"
    "uqc834C0Es3ye1fdrNQgjlVuc565AGTL8r7iFONTPhiCwK5XQTp3CfyAPbvSM/zRPeX5AaKRaCWa"
    "s4FZ1hTvvJIhXxUf0h5dWsPjOqi/PQLKX3uAmSWGxEgAKRoAJQqAaCLaiEaiNRWy7I3+WUznEWMu"
    "ANxSGmTChFnOMJ0lxVDeuACBnx8sySTYrKhn+KN7yisaSAvRRLRlGjlkYSeJeH3/VDcPGwmcSq4W"
    "pEorrbGPhqdMAj16Uagsg9is5NAaqaniecWAaCBaiKZsUAStRn9/2bkXBMCSAsgjTkdqFnj+zaJN"
    "oube5EQl1lj4RMtReaJhOpVPhXd3mbkbJgKnSQ0IBPIf97na4VTXfLIduco/QBJpSC6YaubRxCzv"
    "7bwpld/bnfOti1CDSZ7Q2F0BCIshOO1mogmoBQihGJOIVieHvWgsz0UO5K/yIogX0awlkVc317Je"
    "FSvR4YRCUKhJRKqTXj9SlXsEKFTlRaTygvM8l1dXAOdPvn4UdWPESQdDxR3zcUeJq6NZy3mGwVyR"
    "YWzL8fLFIBRO8oLqf63vZNcJJ50y3kmuZAJoM5KUf3RHBKmnuju7SWjlSaK0sszC5muH3YWpvKc+"
    "Oj/xvBGqv0fTPRzawkNaGpSVFz85kRPmlEm8+DYwPX0XuTaYnAdoSvqBKKpDdakNaqtY0IkSETYw"
    "jwA8410CpP0YWCYD5h6jIlqFsfURT2ywUCj/+hCkD6/xlSA0JFU9pibtUlNTHC6p/N5/gnx5BEqB"
    "xE+SeBysNSLf2i9meDSAzt4xYH92H6LnrNBKX6QQI9wkjk1FaIJ0AkzwypocgqA0laYyXOVLZJ5A"
    "Z4kk7+myPw0cOzbpoS21km4mtmMkwQ0Ilkeqcs4M8wE3CQqPvfBv0CzvRIuEodkqf0ZlSlF5tz96"
    "eRHh5SFPCTP+dGq5aafOLW2dz+CjnzjpcYytj41kX10VArWxDpp+9BhAHLfcVHwHqgLnf/03MPv9"
    "60OrrMOXJ9i/DTt6ew7+IrXctAKgoyWKNv9/+JhHTmiddHP4CujxCfALLIAx/keWgxRQQHn5JK5I"
    "/Qu60LhfWTNLOCPAPj5XnrgPurvTVGta3R4aGrLq59xPJ7a3UZoaCpdV8FC5X6dDJJuBgsEWufcS"
    "v/cLNOujk2OeXSwGTwy+fbh3uvIZjXvw8sWzDXPvW4gttXCCSQjhCMQnx0oaFWYSUyfG5nkXPgxe"
    "OtfT9bNMdXIGXpvbOo/QAQMnTaex6EDS3SYEGvJq6jHyrIoHw9gbvce7NmSrl3OqZ6hjW3FofNdJ"
    "Uwex+vnTn9m9QyBaiCaReaT5gq6ObctVN6/Q+8LVa+cGreBJ8awgnRgbGf4E9938c4zFgNYs5PBE"
    "tUfmrxq6veK9M69fzlU/r8n++8eOXLJsewOdwHQrYofkbMoiPkZzC0R5RTWnIcXmB2yQ1+bDPKGg"
    "zZcFyzfVhQPsNdSEVjF/6mTWEN+D+zRAnj5aVZf2UQWO1j22wjYWcmK84N2nlStXBnSlbh/WfNTb"
    "OYP4xCg/ljJTBynJy0eiMRySI+mHNRjsC1pD3zx16pRRSJtFb781rercjqPDc3QOT8ynL0Umx2/y"
    "jybAp5GCL2q0GiiriKZ9OUIHIdHmd5w/0bUHikBJ3wyhEJbim3geG1mT+oycpKnHce9v6jL4ub08"
    "JzwoVVJvOvUZDJahytMnM+mkIvNv2ox9P9+j8dN2BT6Avg3Eln6JGvFgtnL0fYFp6fwIm2UY/CMq"
    "hhVpGFPx4r9KkH9AlQO9ls22I+MHoUT4+d2g3NzW8Q0UwrPOGsJ3oIfHrd2dOLmhU+C+2JfvH05y"
    "JynHVjMZNmKoeRNmLZXSPFZ+oB0crHkGbbxLsuFgb0/l0WK/DsuEmf90tm1dgwTqZmRlOSYbscd7"
    "8U02iucRCbe/EO1HgvrRU/TjC/6Pyay/Xzhx+DrMIGZcAJlA+/NWyEaBmGzCMPr73+me2c/NMuCO"
    "CeBuwf8BAAD//+EJOpwAAAAGSURBVAMAf5LafFnNp7gAAAAASUVORK5CYII="
)


def imagen_icono(maestro: tk.Misc) -> tk.PhotoImage:
    """Construye el `PhotoImage` del icono para el intérprete de `maestro`.

    Se decodifica en cada llamada a propósito: un `PhotoImage` pertenece al
    intérprete Tk que lo creó, así que reutilizar una instancia global fallaría
    al crear una segunda ventana o en los tests, donde cada caso levanta su
    propio `tk.Tk()`. Decodificar 4 KiB es despreciable frente a ese riesgo.
    """
    datos = base64.b64decode(_ICONO_PNG_B64)
    return tk.PhotoImage(master=maestro, data=datos)


def aplicar_icono(ventana: tk.Tk) -> tk.PhotoImage | None:
    """Pone el isotipo como icono de `ventana` y devuelve la imagen, o `None`.

    Devuelve la imagen para que quien llame la conserve: Tk no retiene una
    referencia fuerte y, si se descarta, el icono desaparece en cuanto el
    recolector de basura pasa. `iconphoto` establece el icono por defecto de
    todas las ventanas del proceso, incluidos los `Toplevel` de los diálogos.

    No lanza si Tk no soporta la operación: en un entorno sin gestor de ventanas
    (por ejemplo `xvfb` en CI) el icono es lo de menos y un fallo aquí no debe
    impedir que la aplicación arranque.
    """
    try:
        imagen = imagen_icono(ventana)
        ventana.iconphoto(True, imagen)
        return imagen
    except tk.TclError:
        return None
