import json
import os

class MetadataManager:
    def __init__(self, storage_path="metadata_registry.json"):
        self.storage_path = storage_path
        self.registry = self.load()

    def load(self):
        if os.path.exists(self.storage_path):
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"columns": {}, "lineage": {}, "context": {}}

    def save(self):
        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(self.registry, f, indent=4, ensure_ascii=False)

    def register_column(self, name, business_name, description=None):
        self.registry["columns"][name] = {
            "business_name": business_name,
            "description": description
        }
        self.save()

    def register_lineage(self, target, sources, operation, reason):
        self.registry["lineage"][target] = {
            "sources": sources,
            "operation": operation,
            "reason": reason
        }
        self.save()

    def translate(self, name):
        # 优先查找血缘描述
        if name in self.registry["lineage"]:
            item = self.registry["lineage"][name]
            return f"{name} (由 {item['sources']} 衍生: {item['operation']})"
        # 其次查找业务字典
        if name in self.registry["columns"]:
            return f"{self.registry['columns'][name]['business_name']} ({name})"
        return name

if __name__ == "__main__":
    # 简单的 CLI 接口供脚本调用
    import sys
    manager = MetadataManager()
    if sys.argv[1] == "register":
        manager.register_column(sys.argv[2], sys.argv[3])
