-- 为受控的“查看密码”操作增加可解密密文；登录仍使用password_hash校验。
ALTER TABLE iam.user_account
    ADD COLUMN IF NOT EXISTS password_ciphertext BYTEA,
    ADD COLUMN IF NOT EXISTS password_nonce BYTEA;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'iam.user_account'::regclass
          AND conname = 'ck_iam_user_password_cipher_pair'
    ) THEN
        ALTER TABLE iam.user_account
            ADD CONSTRAINT ck_iam_user_password_cipher_pair
            CHECK ((password_ciphertext IS NULL) = (password_nonce IS NULL));
    END IF;
END $$;

COMMENT ON COLUMN iam.user_account.password_ciphertext IS '用户密码AES-GCM认证加密密文；仅供具备查看密码权限的服务端临时解密，禁止列表接口返回。';
COMMENT ON COLUMN iam.user_account.password_nonce IS '用户密码AES-GCM随机nonce；须与password_ciphertext成对保存，不能单独解密。';

INSERT INTO iam.permission_resource (
    resource_code, resource_name, resource_type, module_code,
    parent_resource_id, route_path, display_order, is_active, updated_at
)
SELECT 'system.user.password.view', '查看用户密码', 'action', 'system',
       parent.resource_id, NULL, 21, TRUE, NOW()
FROM iam.permission_resource parent
WHERE parent.resource_code = 'system.user.manage'
ON CONFLICT (resource_code) DO UPDATE SET
    resource_name = EXCLUDED.resource_name,
    resource_type = EXCLUDED.resource_type,
    module_code = EXCLUDED.module_code,
    parent_resource_id = EXCLUDED.parent_resource_id,
    route_path = EXCLUDED.route_path,
    display_order = EXCLUDED.display_order,
    is_active = TRUE,
    updated_at = NOW();
