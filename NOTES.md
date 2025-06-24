### Create standalone binary for Mac
```bash
pyinstaller \
  --onefile \
  --name zero_config_dlna \
  --add-data "mime.types:." \
  app.py
```
