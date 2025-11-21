-- Migration: Add rate limiting columns to users table
-- Created: 2025-10-31

-- Add usage tracking columns
ALTER TABLE users
ADD COLUMN IF NOT EXISTS daily_requests_used INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS monthly_requests_used INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS ai_tokens_used INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS last_request_date DATE,
ADD COLUMN IF NOT EXISTS custom_limits JSONB;

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_users_last_request_date ON users(last_request_date);

-- Add comment
COMMENT ON COLUMN users.daily_requests_used IS 'Number of AI requests used today';
COMMENT ON COLUMN users.monthly_requests_used IS 'Number of AI requests used this month';
COMMENT ON COLUMN users.ai_tokens_used IS 'Total AI tokens consumed this month';
COMMENT ON COLUMN users.last_request_date IS 'Date of last AI request (for auto-reset)';
COMMENT ON COLUMN users.custom_limits IS 'Custom rate limits override (JSONB)';
