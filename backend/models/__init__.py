"""模型页（设计文档 5、D21、D22）：模型全部在网关数据库里，页面上增删改；
首次启动从 config/seed/models.yaml 导入默认的几个。
"""

from backend.models.schemas import DefaultInput, ModelInput, ModelsView, ModelView
from backend.models.service import ModelAdmin

__all__ = ["DefaultInput", "ModelAdmin", "ModelInput", "ModelView", "ModelsView"]
