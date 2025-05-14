-- SQL-скрипт для обновления базы данных

-- Создание таблицы для хранения настроек расписания
CREATE TABLE IF NOT EXISTS schedule_settings (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    value VARCHAR(255) NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Добавление настроек часового пояса (по умолчанию - московское время)
INSERT INTO schedule_settings (name, value, description)
VALUES 
('timezone', 'Europe/Moscow', 'Часовой пояс для планирования публикаций (например, Europe/Moscow)')
ON CONFLICT (name) DO NOTHING;

-- Добавление настроек времени публикации
INSERT INTO schedule_settings (name, value, description)
VALUES 
('publish_time_1', '09:00', 'Первое время публикации (формат ЧЧ:ММ)'),
('publish_time_2', '12:00', 'Второе время публикации (формат ЧЧ:ММ)'),
('publish_time_3', '18:00', 'Третье время публикации (формат ЧЧ:ММ)')
ON CONFLICT (name) DO NOTHING;