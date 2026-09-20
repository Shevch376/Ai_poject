[app]

# (str) Title of your application
title = FrontWP

# (str) Package name (только маленькие латинские буквы)
package.name = frontwp

# (str) Package domain (нужно для Android/iOS)
package.domain = org.example

# (str) Source code where the main.py live
source.dir = .

# (str) Main entry point
source.main = main.py

# (list) Source files extensions to include
source.include_exts = py,kv,png,jpg,ttf,ico,json

# (list) List of inclusions using pattern matching
# Ресурсы из папок Welcome и flags
source.include_patterns = assets/Welcome/**/*, assets/flags/**/*

# (str) Application version
version = 0.1

# (list) Application requirements (Python packages)
requirements = python3,kivy,kivymd,requests,websocket-client,pyjnius

# (list) Supported orientations
orientation = portrait

# (bool) Fullscreen
fullscreen = 0

# (list) Permissions
# Если нужно интернет или другое, например:
android.permissions = INTERNET, RECORD_AUDIO
android.manifest.application_activity_windowSoftInputMode = adjustResize
android.allow_cleartext = True

# Google Sign-In for Android mobile auth.
android.gradle_dependencies = com.google.android.gms:play-services-auth:21.2.0
android.enable_androidx = True


[buildozer]

# (int) Log level (0 = error, 1 = info, 2 = debug)
log_level = 2

# (int) Display warning if buildozer is run as root
warn_on_root = 1

# (list) Android architectures to build for
android.archs = arm64-v8a, armeabi-v7a

# (int) Minimum API your APK will support
android.minapi = 21

# (int) Target Android API
android.api = 33

# (int) Android SDK version
android.sdk = 33

# (str) Android NDK version
android.ndk = 25b

# (int) Android NDK API
android.ndk_api = 21

# (bool) Enable Android auto backup feature
android.allow_backup = True
