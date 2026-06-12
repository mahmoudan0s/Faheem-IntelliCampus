from enum import Enum

class ProcessingEnum(str, Enum): 
    
    TXT = ".txt"
    PDF = ".pdf"
    PNG = ".png"
    JPG = ".jpg"
    JPEG = ".jpeg"
    BMP = ".bmp"
    # This enum can be used to define the supported file types for processing,
    #  and their corresponding loaders. This way we can easily add support for 
    # new file types in the future by simply adding them to the enum and
    #  implementing their loaders.  