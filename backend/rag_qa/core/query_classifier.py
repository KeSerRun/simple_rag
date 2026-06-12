# 导入标准库
import json
import os
# 导入 PyTorch 库
import torch
# 导入日志记录器
from base.logger import logger
# 导入配置
from base.config import conf
# 导入分词器和分类模型
from transformers import BertTokenizer, BertForSequenceClassification
# 导入训练器和训练参数
from transformers import Trainer, TrainingArguments
# 导入数据处理库
from sklearn.model_selection import train_test_split
# 导入评估指标
from sklearn.metrics import classification_report, accuracy_score

'''
使用 BERT 模型进行意图识别，实际上是一个分类问题，需要对 BERT 模型进行 LoRA 微调。
需要安装 BERT-BASE-CHINESE 模型：
modelscope download --model google-bert/bert-base-chinese --local_dir ./model/bert-base-chinese
'''

class QueryClassifier:
    def __init__(self, model_path: str,     # 模型路径
                 label_list: list = None,          # 分类标签列表
                 pretrained_model: str = None,   # 如果需要训练模型，提供预训练模型路径
                 train_data_file: str = None,   # 训练数据文件路径
                 eval_data_file: str = None,    # 评估数据文件路径
                 device: str = 'cpu'):           # 设备类型
        # 初始化模型
        self.model_path = model_path
        # 加载 BERT 分词器
        self.tokenizer = None
        # 初始化模型
        self.model = None
        # 初始化训练模型
        self.pretrain_model = pretrained_model
        # 确定设备
        self.device = device
        # 训练数据文件路径
        self.train_data_file = train_data_file
        # 评估数据文件路径
        self.eval_data_file = eval_data_file
        # 分类标签列表
        self.label_list = label_list
        # 定义标签映射
        self.label_map = {k: v for v, k in enumerate(label_list)} if label_list else {}
        # 加载模型
        self.load_model()

    def load_model(self):
        # 检查模型路径是否存在
        if os.path.exists(self.model_path):
            '''已经训练过模型，直接加载'''
            # 加载模型
            self.model = BertForSequenceClassification.from_pretrained(self.model_path).to(self.device)
            # 加载分词器
            self.tokenizer = BertTokenizer.from_pretrained(self.model_path,device=self.device)
            # 如果标签映射为空，从模型配置中提取标签映射
            if self.label_map == {}:
                self.label_map = {int(k): v for k, v in self.model.config.id2label.items()}
        else:
            '''模型路径不存在，初始化新模型'''
            # 如果预训练模型路径不存在，记录错误日志并抛出异常
            if not self.pretrain_model or not os.path.exists(self.pretrain_model):
                logger.error(f"预训练模型路径不存在: {self.pretrain_model}")
                raise FileNotFoundError(f"预训练模型路径不存在: {self.pretrain_model}")
            # 初始化一个新的模型, 指定分类标签数量
            self.model = BertForSequenceClassification.from_pretrained(self.pretrain_model, num_labels=len(self.label_map)).to(self.device)
            # 加载分词器
            self.tokenizer = BertTokenizer.from_pretrained(self.pretrain_model, device=self.device)
            # 记录初始化新模型的日志
            logger.warning(f"模型路径不存在，初始化新模型: {self.pretrain_model}")
            # 记录开始训练模型的日志
            logger.info("开始训练模型...")
            # 训练模型
            self.train_model()

    def train_model(self):
        '''训练模型'''
        # 加载训练数据
        try:
            with open(self.train_data_file, 'r', encoding='utf-8') as f:
                data = [json.loads(line) for line in f.readlines()]
        except Exception as e:
            logger.error(f"加载训练数据失败: {e}")
            raise
        # 提取问题和标签
        questions = [item['query'] for item in data]
        labels = [item['label'] for item in data]
        # 数据划分
        train_text, val_text, train_label, val_label = train_test_split(questions, labels, test_size=0.2, random_state=42)
        # 数据预处理
        x_train_encodings, y_train_encodings = self.preprocess_data(train_text, train_label)
        x_val_encodings, y_val_encodings = self.preprocess_data(val_text, val_label)
        # 创建数据集
        train_dataset = self.create_dataset(x_train_encodings, y_train_encodings)
        val_dataset = self.create_dataset(x_val_encodings, y_val_encodings)
        # 定义训练参数
        training_args = TrainingArguments(
            output_dir=self.model_path,   # 输出目录
            num_train_epochs=3,                            # 训练轮数
            per_device_train_batch_size=16,                # 每个设备的训练批次大小
            per_device_eval_batch_size=64,                 # 每个设备的评估批次大小
            eval_strategy='epoch',                         # 评估策略,每轮评估一次
            save_strategy='epoch',                         # 梯度检查点保存策略,每轮保存一次
            save_total_limit=1,                            # 最多保存模型数量
            logging_steps=10,                              # 日志记录步数
            warmup_steps=500,                              # 预热步数
            weight_decay=0.01,                             # 权重衰减
            load_best_model_at_end=True,                   # 训练结束后加载最佳模型
            fp16=torch.cuda.is_available(),                # 是否使用混合精度训练
            metric_for_best_model='eval_loss',             # 评估最佳模型的指标
        )
        # 创建 Trainer
        trainer = Trainer(
            model=self.model,                     # 训练的模型
            args=training_args,                   # 训练参数
            train_dataset=train_dataset,          # 训练数据集
            eval_dataset=val_dataset,             # 验证数据集
            compute_metrics=self.compute_metrics  # 评估指标计算函数
        )
        # 开始训练
        trainer.train()
        # 保存最优模型
        self.save_model(self.model_path)

    def evaluate_model(self):
        # 加载评估数据
        try:
            with open(self.eval_data_file, 'r', encoding='utf-8') as f:
                data = [json.loads(line) for line in f.readlines()]
        except Exception as e:
            logger.error(f"加载评估数据失败: {e}")
            raise
        # 提取问题和标签
        questions = [item['query'] for item in data]
        labels = [item['label'] for item in data]
        # 数据预处理
        x_eval_encodings, y_eval_encodings = self.preprocess_data(questions, labels)
        # 创建数据集
        eval_dataset = self.create_dataset(x_eval_encodings, y_eval_encodings)
        # 创建 Trainer
        trainer = Trainer(
            model=self.model,
            args=TrainingArguments(output_dir=self.model_path),
            eval_dataset=eval_dataset,
            compute_metrics=self.compute_metrics
        )
        # 评估模型
        results = trainer.evaluate()
        # 记录评估结果的日志
        logger.info(f"评估结果: {results}")

    '''预测函数，输入一个查询，输出预测的标签'''
    def predict(self, query: str):
        '''
        Returns:
            LABEL_0, LABEL_1, ...
        '''
        # 设置模型为评估模式
        self.model.eval()  
        # 使用 torch.no_grad() 上下文管理器，禁用梯度计算，以节省内存和加速推理过程
        with torch.no_grad():
            # 对输入查询进行分词和编码，返回 PyTorch 张量
            inputs = self.tokenizer(query, return_tensors='pt', truncation=True, padding='max_length', max_length=128)
            # 将输入移动到指定设备
            inputs = {key: val.to(self.device) for key, val in inputs.items()}  # 将输入移动到设备
            # 进行前向传播，获取模型输出
            outputs = self.model(**inputs)
            # 从模型输出中获取 logits，并计算预测的标签 ID
            logits = outputs.logits
            # 使用 torch.argmax() 函数获取预测的标签 ID
            predicted_label_id = torch.argmax(logits, dim=-1).item()
            # 将预测的标签 ID 转换为对应的标签名称
            predicted_label = self.label_list[predicted_label_id]
            # 返回预测的标签
            return predicted_label

    def preprocess_data(self, text: str, label: int):
        # 数据预处理
        train_encodings = self.tokenizer(
            text, 
            truncation=True, 
            padding='max_length', 
            max_length=128,
            return_tensors='pt'
        )
        return train_encodings, [self.label_map[label] for label in label]

    def create_dataset(self, encodings, labels):
        '''创建 PyTorch 数据集'''
        class Dataset(torch.utils.data.Dataset):
            def __init__(self, encodings, labels):
                self.encodings = encodings
                self.labels = labels

            def __len__(self):
                return len(self.labels)

            def __getitem__(self, idx):
                item = {key: val[idx] for key, val in self.encodings.items()}
                item['labels'] = torch.tensor(self.labels[idx])
                # 返回字典形式的数据项，包含输入编码和标签，以便于训练器使用
                return item
        return Dataset(encodings, labels)

    def compute_metrics(self, eval_pred):
        # 计算评估指标
        logits, labels = eval_pred
        predictions = torch.argmax(torch.tensor(logits), dim=-1)
        report = classification_report(labels, predictions, target_names=list(self.label_map.values()), output_dict=True)
        '''返回评估指标，包括精确率、召回率和 F1 分数，使用加权平均的方式计算，以适应不平衡数据集的情况。'''
        return {
            'accuracy': accuracy_score(labels, predictions),
            'precision': report['weighted avg']['precision'],
            'recall': report['weighted avg']['recall'],
            'f1': report['weighted avg']['f1-score']
        }

    def save_model(self, save_path):
        # 保存模型
        self.model.save_pretrained(save_path)
        # 保存分词器
        self.tokenizer.save_pretrained(save_path)
        # 记录保存模型的日志
        logger.info(f"模型已保存到: {save_path}")

def start_train():
    # 创建 QueryClassifier 实例
    classifier = QueryClassifier(
        model_path=conf.query_classifier_model, 
        pretrained_model=conf.query_classifier_pretrained,
        train_data_file=conf.query_classifier_train_data_file,
        eval_data_file=conf.query_classifier_eval_data_file,
        label_list=conf.query_classifier_label_list,
        device='cuda' if torch.cuda.is_available() else 'cpu'
    )
    # 训练模型
    classifier.train_model()
    # 评估模型
    classifier.evaluate_model()

if __name__ == "__main__":
    q = QueryClassifier(model_path=conf.query_classifier_model, 
                        pretrained_model=conf.query_classifier_pretrained,
                        train_data_file=conf.query_classifier_train_data_file,
                        eval_data_file=conf.query_classifier_eval_data_file,
                        label_list=conf.query_classifier_label_list)
    q.load_model()
    q.predict("什么是人工智能？")
    q.predict("请帮我解答一下专业的医学问题。")
    q.predict("今天天气怎么样？")
    q.predict("请问一下专业的法律问题。")