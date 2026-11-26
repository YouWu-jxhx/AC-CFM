# 用户指南

`accfmlab.run` 和 `accfmlab.batch` 共用持久化逻辑。事故行号以原算例矩阵为准。先做 N-0 和基准工况的验收，再生产实验样本。

```matlab
cfg = accfmlab.config();
cfg.load_scale = 1.05;
cfg.protection.dP_limit = 0.15;
prepared = accfmlab.prepare(cfg);
disp(prepared.audit)

cfg.record_states = true;
cfg.output_dir = fullfile(pwd,'runs','load105-pilot');
faults = [accfmlab.fault(),accfmlab.fault(1),accfmlab.fault(9), ...
          accfmlab.fault([1 9]),accfmlab.fault([],1),accfmlab.fault([],[],2)];
manifest = accfmlab.scenarios(faults,cfg.seed);
summary = accfmlab.batch(cfg,manifest);
disp(summary(:,{'scenario_id','status','lost_mw','pf_count'}))
```

母线事故以 `BUS_I` 指定，将该母线、负荷、本地机组和相邻支路置为停运。若支路或机组也被显式指定，等效停运集合按并集记录。原事故、模型动作、停岛波及在数据中用各自字段表示。

每个批次固定算例、负荷规模、调度流程和保护设置。对照实验用相同清单、不同的批次目录和受控的配置差异。对比时先找首个不同岛或保护事件，再看终态损失。用于训练前按计划、事故分组划分数据，避免把同一物理试验的不同图随机标签分到训练和验证两侧。
