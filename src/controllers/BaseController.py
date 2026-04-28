from helpers.confg import get_settings,Settings
import os
import random,string
class BaseController:

    def __init__(self):
        self.app_settings = get_settings()
        #this will give us the absolute path to the base directory of the project
        self.base_dir = os.path.dirname(os.path.dirname(__file__))
        self.file_dir=os.path.join(
            self.base_dir,
            "assets/files"
            )
       # self.file_dir =self.base_dir + "/assets/files"
    
    def generate_random_string(self, length :  int = 12) -> str:
        """Generate a random string of fixed length."""
        letters = string.ascii_letters + string.digits
        return ''.join(random.choice(letters) for i in range(length))