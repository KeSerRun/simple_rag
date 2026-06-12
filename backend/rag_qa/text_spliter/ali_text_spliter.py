from base.config import conf  # 导入全局配置实例
from base.logger import logger  # 导入日志记录器实例
from langchain_text_splitters import CharacterTextSplitter
import re
from typing import List
from modelscope import pipeline   # 阿里巴巴开源的模型平台
from transformers import BertConfig

# 加载前给 BertConfig 添加缺失的属性
if not hasattr(BertConfig, 'is_decoder'):
    BertConfig.is_decoder = property(lambda self: getattr(self, '_is_decoder', False))

'''
使用阿里巴巴开源的模型平台（ModelScope）进行文本切分，适用于中文文档，特别是PDF格式的文本。
需要安装ModelScope库并下载相应的模型：
    modelscope download --model iic/nlp_bert_document-segmentation_chinese-base --local_dir ./model/nlp_bert_document-segmentation_chinese-base
'''

class AliTextSplitter(CharacterTextSplitter):
    def __init__(self, model: str, pdf: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.model = model
        self.pdf = pdf
        # Initialize the pipeline here or ensure it's initialized before split_text is called
        # Consider adding error handling for model loading
        try:
            self.pipeline = pipeline(
                task="document-segmentation",
                model= self.model,  # Use the model path from config
            )
        except Exception as e:
            logger.error(f"Error initializing ModelScope pipeline: {e}")
            logger.warning("Please check if the model path is correct and if the model is downloaded.")
            logger.warning("1. modelscope download --model iic/nlp_bert_document-segmentation_chinese-base --local_dir ./model/nlp_bert_document-segmentation_chinese-base")
            logger.warning("2. Ensure the model path in config.ini is correct.")
            logger.warning("path should be: model/nlp_bert_document-segmentation_chinese-base")
            self.pipeline = None
            raise

    def split_text(self, text: str) -> List[str]:
        if not self.pipeline:
            logger.warning("ModelScope pipeline not initialized. Returning empty list.")
            return []

        # Preprocessing specific to PDF text if needed
        if self.pdf:
            text = re.sub(r"\n{3,}", r"\n", text)
            # Replace multiple spaces with a single space
            text = re.sub(r'\s+', " ", text)
            # Consider removing single newlines carefully, might merge unrelated lines
            # text = text.replace("\n", " ") # This might be too aggressive
            text = re.sub("\n\n", "\n", text) # Keep paragraph breaks


        try:
            result = self.pipeline(documents=text)
            # The default output format might be a single string with "\n\t" separators
            sent_list = [segment.strip() for segment in result["text"].split("\n\t") if segment.strip()]
            return sent_list
        except Exception as e:
            logger.error(f"Error during ModelScope document segmentation: {e}")
            # Fallback behavior: maybe split by paragraph or return the original text in a list
            return text.split('\n\n') # Simple fallback


if __name__ == '__main__':
    # Example usage requires modelscope and relevant model downloaded
    # pip install "modelscope[nlp]" tensorflow torch -f https://modelscope.oss-cn-beijing.aliyuncs.com/releases/repo.html

    sample_text = """移动端语音唤醒模型，检测关键词为“小云小云”。
模型主体为4层FSMN结构，使用CTC训练准则，参数量750K，适用于移动端设备运行。

模型输入为Fbank特征，输出为基于char建模的中文全集token预测，测试工具根据每一帧的预测数据进行后处理得到输入音频的实时检测结果。
模型训练采用“basetrain + finetune”的模式，basetrain过程使用大量内部移动端数据，在此基础上，使用1万条设备端录制安静场景“小云小云”数据进行微调，得到最终面向业务的模型。
后续用户可在basetrain模型基础上，使用其他关键词数据进行微调，得到新的语音唤醒模型，但暂时未开放模型finetune功能。"""

    # Assuming MODEL_PATH is correctly configured and modelscope is installed
    model_split = AliTextSplitter(model=conf.segment_model, pdf=False)
    result = model_split.split_text(text=sample_text)
    print(result)
    # Expected output (example, actual output depends on the model):
    # ['移动端语音唤醒模型，检测关键词为“小云小云”。', '模型主体为4层FSMN结构，使用CTC训练准则，参数量750K，适用于移动端设备运行。', '模型输入为Fbank特征，输出为基于char建模的中文全集token预测，测试工具根据每一帧的预测数据进行后处理得到输入音频的实时检测结果。', '模型训练采用“basetrain + finetune”的模式，basetrain过程使用大量内部移动端数据，在此基础上，使用1万条设备端录制安静场景“小云小云”数据进行微调，得到最终面向业务的模型。', '后续用户可在basetrain模型基础上，使用其他关键词数据进行微调，得到新的语音唤醒模型，但暂时未开放模型finetune功能。']