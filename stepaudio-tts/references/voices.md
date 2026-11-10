# 官方音色速查（StepAudio 2.5 TTS，`--voice` 用）

## 国际版文档明列的系统音色（推荐优先使用）

来源：platform.stepfun.ai 开发者指南「System Voice ID List」，Supported Models 均为 `stepaudio-2.5-tts`。

| 音色 ID | 名称 | 推荐场景 |
| --- | --- | --- |
| zixinnansheng | Confident Male（自信男声） | 有声书、情感陪伴、教育、营销 |
| elegantgentle-female | Elegant Gentle（气质温婉） | 客服、口播、教育、情感陪伴 |
| livelybreezy-female | Lively Breezy（活力轻快） | 情感陪伴、客服、教育、营销 |
| vibrant-youth | Vibrant Youth | 有声书、视频配音 |
| lively-girl | Lively Girl | 有声书、视频配音 |
| soft-spoken-gentleman | Soft-spoken Gentleman | 情感陪伴、有声书 |
| magnetic-voiced-male | Magnetic-voiced Male | 有声书、视频配音 |

说明：
- 脚本 `--voice` 默认 `elegantgentle-female`。
- 国际版文档的 2.5-tts 示例中也出现过 `cixingnansheng`（未列入上面的系统音色表，可用性以实测为准）。
- 查询接口：`GET {base}/audio/system_voices?model=step-tts-2`（base = `https://api.stepfun.ai/step_plan/v1`）。
- 音色复刻：约 3 秒参考音频即可复刻（`POST {base}/audio/voices`，试听用 `/audio/voices/preview`），复刻音色同样支持 `instruction` 语境控制。
- 输出语言：中文 / 英文 / 中英混合 / 日语。

## 其他常见音色（国内平台文档收录；国际版是否可用未在文档中确认）

若调用时报音色相关错误，说明该音色在当前平台不可用，请换用上表的国际版明列音色。

| 音色 ID | 名称 | 描述 | 推荐场景 |
| --- | --- | --- | --- |
| boyinnansheng | 播音男声 | 男，播音腔，中正平稳 | 有声书、口播 |
| cixingnansheng | 磁性男声 | 男，深情厚重，有感染力，霸总感 | 有声书、情感陪伴 |
| energeticconfident-female | （英文音色） | 女，英文音色，有活力且自信 | 客服、语音助手 |
| ganliannvsheng | 干练女声 | 女，沉稳冷静、慢条斯理，专业感强 | 客服、语音助手 |
| huolinvsheng | 活力女声 | 女，轻盈有活力，亲和力强 | 客服、语音助手 |
| jilingshaonv | 机灵少女 | 女，声线细腻，有活力 | 语音助手、口播 |
| jingdiannvsheng | 经典女声 | 女，语速较慢，真诚温柔 | 客服、情感陪伴 |
| lengyanyujie | 冷艳御姐 | 女，播音感，专业不失亲和 | 视频配音 |
| linjiajiejie | 邻家姐姐 | 女，有亲和力，邻家大姐姐，给人安全感 | 口播、情感陪伴、语音助手、视频配音 |
| linjiameimei | 邻家妹妹 | 女，可爱亲和，稚气感 | 视频配音、口播、语音助手 |
| qingchunshaonv | 清纯少女 | 女，温柔，轻盈有活力，亲和力强 | 客服、语音助手 |
| qingniandaxuesheng | 青年大学生 | 男，沉稳厚实，播音专业感 | 口播 |
| qinhenvsheng | 亲和女声 | 女，冷静温柔、有亲和力 | 客服、语音助手 |
| qinqienvsheng | 亲切女声 | 女，温柔带点甜美，亲和力强，邻家感 | 口播、情感陪伴、语音助手 |
| ruanmengnvsheng | 软萌女声 | 女，可爱、甜、嗲 | 情感陪伴、语音助手、视频配音 |
| ruyananshi | 儒雅男士 | 男，沉稳厚重，叙述感强，有亲和力、陪伴感 | 有声书、情感陪伴、口播、语音助手 |
| shenchennanyin | 深沉男音 | 男，有感情，代入感强，给人信心 | 情感陪伴、有声书 |
| shuangkuaijiejie | 爽快姐姐 | 女，清澈有活力 | 口播、语音助手 |
| shuangkuainansheng | 爽快男声 | 男，沉稳冷静、慢条斯理，专业感强 | 客服、语音助手 |
| tianmeinvsheng | 甜美女声 | 女，甜美温柔，亲和力强 | 情感陪伴、客服 |
| wenjingxuejie | 文静学姐 | 女，冷静沉稳，吐字清晰稳定 | 口播、语音助手 |
| wenrougongzi | 温柔公子 | 男，沉稳温柔，叙述感强 | 情感陪伴、有声书 |
| wenrounansheng | 温柔男声 | 男，温柔亲和 | 口播、情感陪伴、客服、教育 |
| wenrounvsheng | 温柔女声 | 女，温柔甜美，叙述感强，有关怀感 | 有声书、情感陪伴 |
| wenroushunv | 温柔熟女 | 女，成熟稳重，温柔有亲和力 | 客服、口播、教育 |
| yingwennansheng | 英文男声 | 英文音色 | 英文内容 |
| yingwennvsheng | 英文女声 | 英文音色 | 英文内容 |
| youyanvsheng | 优雅女声 | 女，成熟亲和，给人踏实感 | 视频配音 |
| yuanqinansheng | 元气男声 | 男，情绪饱满有活力 | 有声书、口播 |
| yuanqishaonv | 元气少女 | 女，声线细腻，甜、嗲 | 情感陪伴、语音助手 |
| zhengpaiqingnian | 正派青年 | 男，有感染力、说服力和亲和力，有激情和鼓动性 | 营销 |
| zhixingjiejie | 知性姐姐 | 女，成熟沉稳，叙述有画面感 | 视频配音、口播、语音助手 |
