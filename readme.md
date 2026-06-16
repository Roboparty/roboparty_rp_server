rk3588网页后端项目
立项目的
为满足手柄，安卓app，头部，mcp，算力背包等后续前端需求代码的复用性，因此开展此项目。
统一化后端，保证项目一致性，后端运行在rk3588上

立项基础
通过pybind模块，编写网页服务器

需求概览
控制端：
joy键盘映射


回显端：
imu数据
policy名称
电池电量
当前关节错误码

相关接口：

ID	需求编号	需求名称	AT输入	AT输出
1	FR-01	自动识别与连接	AT+CONN?	+CONN: <type>,<status>
2	FR-02	断开检测	AT+CONN?	+CONN: <type>,<status>
3	FR-03	数字按键(需要保证时效性和可靠传输)	AT+BTN=<btn_name>,<state>,<cmd_id>	AT+BTN_RSP=<cmd_id>,<status>[,<timestamp>]
4	FR-04	摇杆输入(需要保证时效性和可靠传输)		
5	FR-09	系统资源监控	AT+SYSINFO?	+SYSINFO: <cpu%>,<mem%>,<Args...>
6	FR-10	机器人主控脚本管理(启动和停止实现可靠传输)		
7	FR-11	Policy状态显示	AT+POLICY?	+POLICY: <name>,<state>
8	FR-12	电机错误码解析(需要保证时效性和可靠传输)		
9	FR-13	IMU数据可视化		