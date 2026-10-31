from __future__ import annotations

from psycopg2.extras import Json

from .base import audit, code, require, text


class PromptService:
    """提示词模板管理；模板只改变分析方式，不参与数据授权。"""

    def __init__(self, database):
        self.database = database

    def prompts(self, context=None, *, admin=False, channel="web"):
        if admin:
            require(context, "ai.prompt.manage")
        with self.database.transaction() as cursor:
            cursor.execute(
                """SELECT p.*,v.prompt_template_version_id,v.template_content,v.output_format,v.change_note
                   FROM ai.prompt_template p
                   JOIN ai.prompt_template_version v ON v.prompt_template_id=p.prompt_template_id
                    AND v.version_no=p.current_version
                   WHERE p.deleted_at IS NULL
                     AND (%s OR (p.is_enabled AND CASE WHEN %s='web' THEN p.web_available ELSE p.feishu_available END))
                   ORDER BY p.sort_order,p.prompt_template_id""",
                (admin, channel),
            )
            rows = [dict(row) for row in cursor.fetchall()]
        if admin:
            return rows
        keys = ("prompt_template_id", "template_code", "template_name", "selection_alias", "description",
                "is_default", "current_version", "prompt_template_version_id")
        return [{key: row[key] for key in keys} for row in rows]

    def save_prompt(self, context, payload, prompt_id=None, *, ip_address="", user_agent=""):
        require(context, "ai.prompt.manage")
        template_code = code(payload.get("template_code"), "模板编码")
        name = text(payload.get("template_name"), "模板名称", maximum=120)
        alias = code(payload.get("selection_alias"), "选择别名")
        content = text(payload.get("template_content"), "模板内容", maximum=30000)
        if any(item in content.lower() for item in ("sk-", "password=", "session_token", "app_secret")):
            raise ValueError("模板内容疑似包含密钥或凭据")
        is_default = bool(payload.get("is_default"))
        with self.database.transaction() as cursor:
            old = None
            if prompt_id:
                cursor.execute("SELECT * FROM ai.prompt_template WHERE prompt_template_id=%s AND deleted_at IS NULL FOR UPDATE", (prompt_id,))
                old = cursor.fetchone()
                if not old:
                    raise ValueError("提示词模板不存在")
                version = int(old["current_version"]) + 1
            else:
                version = 1
            if is_default:
                cursor.execute("UPDATE ai.prompt_template SET is_default=FALSE,updated_at=NOW() WHERE deleted_at IS NULL AND prompt_template_id<>COALESCE(%s,-1)", (prompt_id,))
            values = (template_code, name, alias, text(payload.get("description"), "简介", maximum=500, required=False),
                      bool(payload.get("is_enabled", True)), is_default, bool(payload.get("web_available", True)),
                      bool(payload.get("feishu_available", True)), int(payload.get("sort_order", 100)))
            if prompt_id:
                cursor.execute(
                    """UPDATE ai.prompt_template SET template_code=%s,template_name=%s,selection_alias=%s,description=%s,
                       is_enabled=%s,is_default=%s,web_available=%s,feishu_available=%s,sort_order=%s,current_version=%s,
                       updated_by=%s,updated_at=NOW() WHERE prompt_template_id=%s""",
                    (*values, version, context.user_id, prompt_id),
                )
                saved = prompt_id
            else:
                cursor.execute(
                    """INSERT INTO ai.prompt_template(template_code,template_name,selection_alias,description,is_enabled,is_default,
                       web_available,feishu_available,sort_order,current_version,created_by,updated_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING prompt_template_id""",
                    (*values, version, context.user_id, context.user_id),
                )
                saved = int(cursor.fetchone()["prompt_template_id"])
            cursor.execute(
                """INSERT INTO ai.prompt_template_version(prompt_template_id,version_no,template_content,output_format,change_note,created_by)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (saved, version, content, Json(payload.get("output_format") or {}),
                 text(payload.get("change_note"), "变更说明", maximum=500, required=False), context.user_id),
            )
            audit(cursor, context=context, action="ai.prompt.update" if prompt_id else "ai.prompt.create",
                  target_type="ai.prompt_template", target_id=saved,
                  before={"version": old["current_version"]} if old else None,
                  after={"template_code": template_code, "version": version}, ip_address=ip_address, user_agent=user_agent)
        return {"prompt_template_id": saved, "version": version}

    def toggle_prompt(self, context, prompt_id, *, ip_address="", user_agent=""):
        require(context, "ai.prompt.manage")
        with self.database.transaction() as cursor:
            cursor.execute(
                """UPDATE ai.prompt_template SET is_enabled=NOT is_enabled,updated_by=%s,updated_at=NOW()
                   WHERE prompt_template_id=%s AND deleted_at IS NULL RETURNING template_code,is_enabled""",
                (context.user_id, prompt_id),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("提示词模板不存在")
            audit(cursor, context=context, action="ai.prompt.toggle", target_type="ai.prompt_template", target_id=prompt_id,
                  after={"template_code": row["template_code"], "is_enabled": row["is_enabled"]},
                  ip_address=ip_address, user_agent=user_agent)
        return {"prompt_template_id": prompt_id, "is_enabled": row["is_enabled"]}

    def delete_prompt(self, context, prompt_id, *, ip_address="", user_agent=""):
        require(context, "ai.prompt.manage")
        with self.database.transaction() as cursor:
            cursor.execute(
                """UPDATE ai.prompt_template SET deleted_at=NOW(),is_enabled=FALSE,is_default=FALSE,updated_by=%s,updated_at=NOW()
                   WHERE prompt_template_id=%s AND deleted_at IS NULL RETURNING template_code""",
                (context.user_id, prompt_id),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("提示词模板不存在")
            audit(cursor, context=context, action="ai.prompt.delete", target_type="ai.prompt_template", target_id=prompt_id,
                  before={"template_code": row["template_code"]}, ip_address=ip_address, user_agent=user_agent)
        return {"deleted": True}
