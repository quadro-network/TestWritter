-- MariaDB / MySQL schema (utf8mb4).
-- The database name must match DB_NAME in .env.
--   mysql -h <DB_HOST> -P <DB_PORT> -u <DB_USER> -p < schema.sql

CREATE DATABASE IF NOT EXISTS quiz
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE quiz;

CREATE TABLE IF NOT EXISTS tests (
  id INT NOT NULL AUTO_INCREMENT,
  external_id VARCHAR(128) NULL,
  content_hash VARCHAR(64) NOT NULL,
  title VARCHAR(512) NOT NULL,
  description TEXT NULL,
  tags JSON NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_tests_external_id (external_id),
  UNIQUE KEY uq_tests_content_hash (content_hash),
  KEY ix_tests_external_id (external_id),
  KEY ix_tests_content_hash (content_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS questions (
  id INT NOT NULL AUTO_INCREMENT,
  test_id INT NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  type VARCHAR(32) NOT NULL,
  topic VARCHAR(256) NULL,
  difficulty INT NOT NULL DEFAULT 1,
  question TEXT NOT NULL,
  code_language VARCHAR(64) NULL,
  code_content TEXT NULL,
  options JSON NOT NULL,
  correct JSON NOT NULL,
  explanation TEXT NOT NULL,
  option_explanations JSON NOT NULL,
  PRIMARY KEY (id),
  KEY ix_questions_test_id (test_id),
  CONSTRAINT fk_questions_test
    FOREIGN KEY (test_id) REFERENCES tests (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS attempts (
  id INT NOT NULL AUTO_INCREMENT,
  test_id INT NULL,
  mode VARCHAR(32) NOT NULL,
  tag VARCHAR(128) NULL,
  shuffle TINYINT(1) NOT NULL DEFAULT 0,
  status VARCHAR(32) NOT NULL,
  score_percent FLOAT NULL,
  telegram_user_id VARCHAR(64) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at DATETIME NULL,
  PRIMARY KEY (id),
  KEY ix_attempts_test_id (test_id),
  KEY ix_attempts_telegram_user_id (telegram_user_id),
  CONSTRAINT fk_attempts_test
    FOREIGN KEY (test_id) REFERENCES tests (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS attempt_questions (
  id INT NOT NULL AUTO_INCREMENT,
  attempt_id INT NOT NULL,
  question_id INT NOT NULL,
  sort_order INT NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY uq_attempt_question (attempt_id, question_id),
  KEY ix_attempt_questions_attempt_id (attempt_id),
  KEY ix_attempt_questions_question_id (question_id),
  CONSTRAINT fk_aq_attempt
    FOREIGN KEY (attempt_id) REFERENCES attempts (id) ON DELETE CASCADE,
  CONSTRAINT fk_aq_question
    FOREIGN KEY (question_id) REFERENCES questions (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS answers (
  id INT NOT NULL AUTO_INCREMENT,
  attempt_id INT NOT NULL,
  question_id INT NOT NULL,
  selected JSON NOT NULL,
  is_correct TINYINT(1) NOT NULL,
  answered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_answer_attempt_question (attempt_id, question_id),
  KEY ix_answers_attempt_id (attempt_id),
  KEY ix_answers_question_id (question_id),
  CONSTRAINT fk_answers_attempt
    FOREIGN KEY (attempt_id) REFERENCES attempts (id) ON DELETE CASCADE,
  CONSTRAINT fk_answers_question
    FOREIGN KEY (question_id) REFERENCES questions (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS reminder_settings (
  id INT NOT NULL AUTO_INCREMENT,
  telegram_user_id VARCHAR(64) NOT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 1,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_reminder_telegram_user_id (telegram_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Alembic version table (so the container does not apply 001 again)
CREATE TABLE IF NOT EXISTS alembic_version (
  version_num VARCHAR(32) NOT NULL,
  PRIMARY KEY (version_num)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO alembic_version (version_num)
SELECT '001' FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM alembic_version WHERE version_num = '001');
