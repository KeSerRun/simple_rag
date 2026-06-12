-- ============================================================
-- RAG Simple — MySQL 初始化脚本
-- 由 docker-compose 在首次启动时自动执行
-- ============================================================

CREATE DATABASE IF NOT EXISTS `fqa`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `fqa`;

-- 用户密码表
CREATE TABLE IF NOT EXISTS `user_password` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `username` VARCHAR(30) NOT NULL UNIQUE,
    `password` VARCHAR(30) NOT NULL,
    `role` VARCHAR(20) NOT NULL DEFAULT 'user',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 用户会话表
CREATE TABLE IF NOT EXISTS `user_session` (
    `session_id` VARCHAR(36) PRIMARY KEY,
    `username` VARCHAR(255) NOT NULL,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (username) REFERENCES user_password(username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 问答对表（BM25 检索语料库）
CREATE TABLE IF NOT EXISTS `qa_pairs` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `question` TEXT NOT NULL,
    `answer` TEXT NOT NULL,
    INDEX idx_question (question(511))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 对话历史表
CREATE TABLE IF NOT EXISTS `conversion_history` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `session_id` VARCHAR(36) NOT NULL,
    `user` TEXT NOT NULL,
    `assistant` TEXT NOT NULL,
    `timestamp` TIMESTAMP NOT NULL,
    INDEX idx_session_id (session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
