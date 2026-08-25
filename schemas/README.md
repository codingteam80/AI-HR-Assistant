# Compatibility Notice — Use the Project Root Documentation

This `schemas/` directory contains legacy scaffold/reference material from an
earlier project foundation. It is **not** the authoritative setup guide for the
current AI HR Assistant application.

For current installation, configuration, database setup, Ollama setup, and
runtime instructions, use the files in the **project root**:

- `../README.md` — authoritative setup and execution guide
- `../requirements.txt` — authoritative Python dependency list
- `../DEVELOPER_GUIDE.md` — current developer notes

Do not rely on old foundation-era instructions inside nested scaffold copies.
The live application is started from the project root with:

```powershell
python -m pip install -r requirements.txt
streamlit run app.py
```
