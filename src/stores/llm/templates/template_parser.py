import os

class TemplateParser:

    def __init__(self, language: str=None, default_language='en'):
        self.current_path = os.path.dirname(os.path.abspath(__file__))
        self.default_language = default_language
        self.language = None

        self.set_language(language)

    
    def set_language(self, language: str):# if language is not provided or the provided language is not supported, it will use the default language
        #it uses ar when the user query is in arabic, and en for english, we can expand it later to support more languages
        if not language:
            self.language = self.default_language

        language_path = os.path.join(self.current_path, "locales", language)
        if os.path.exists(language_path):
            self.language = language
        else:
            self.language = self.default_language

    def get(self, group: str, key: str, vars: dict={}):
        if not group or not key:
            return None
        
        group_path = os.path.join(self.current_path, "locales", self.language, f"{group}.py" )
        targeted_language = self.language
        if not os.path.exists(group_path):
            group_path = os.path.join(self.current_path, "locales", self.default_language, f"{group}.py" )
            targeted_language = self.default_language

        if not os.path.exists(group_path):
            return None
        
        # import group module. duck typing to import module by path, we can use importlib but it is more complex and we need
        #  to handle the module name and path, so we can use __import__ which is simpler for our case, but it has some limitations
        #  such as it can not import submodules, but in our case we only have one level of modules so it is fine
        module = __import__(f"stores.llm.templates.locales.{targeted_language}.{group}", fromlist=[group])

        if not module:
            return None
        
        key_attribute = getattr(module, key)
        return key_attribute.substitute(vars)