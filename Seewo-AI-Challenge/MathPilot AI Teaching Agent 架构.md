                    ┌──────────────────────────┐
                    │     教师（Teacher）       │
                    └──────────┬───────────────┘
                               │
                上传试卷 / 查看报告 / 发布讲评
                               │
────────────────────────────────────────────────────────────

                    AI Teaching Orchestrator
                （教学智能调度 Agent）
                               │
      ┌─────────────┬─────────────┬─────────────┐
      │             │             │             │
      ▼             ▼             ▼             ▼

 OCR Agent     Math Reasoning   Knowledge      Teaching
（识别Agent）     Agent         Graph Agent    Strategy Agent
                 （数学推理）    （知识图谱）     （教学策略）

      │             │             │             │
      └─────────────┴─────────────┴─────────────┘
                               │
                    Learning Diagnosis Agent
                       （学情诊断 Agent）
                               │
             ┌─────────────────┴──────────────────┐
             ▼                                    ▼

     Lesson Planning Agent              Exercise Generation Agent
       （讲评生成）                       （练习生成）

             │                                    │
             └─────────────────┬──────────────────┘
                               ▼
                      Classroom Assistant Agent
                        （课堂教学 Agent）

                               │
                               ▼
                        希沃白板 / 教师端