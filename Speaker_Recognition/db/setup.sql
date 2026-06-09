-- One-time MySQL setup for the Speaker Recognition store.
-- Run once with admin rights:   sudo mysql < Speaker_Recognition/db/setup.sql
-- Creates the database and an app user the Python code connects as.
-- (Change the password here and in db_store.py / GO2_DB_PASSWORD if you like.)

CREATE DATABASE IF NOT EXISTS go2_speaker CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'go2'@'localhost' IDENTIFIED BY 'Go2Speaker#2026';
GRANT ALL PRIVILEGES ON go2_speaker.* TO 'go2'@'localhost';
FLUSH PRIVILEGES;
