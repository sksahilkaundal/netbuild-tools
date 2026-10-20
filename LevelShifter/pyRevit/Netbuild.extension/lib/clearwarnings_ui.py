"""WPF layout (XAML) for the "Clear Warnings" button window.

A plain string so it can be checked outside Revit; the button loads it with
``forms.WPFWindow(xaml, literal_string=True)``.  IronPython 2.7 + CPython 3.
"""

from clear_warnings.core import STEPS

_NS = ('xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
       'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"')

_STEP = '''
        <CheckBox x:Name="step_{i}" Content="{label}" IsChecked="True" Margin="0,2"/>'''

_WINDOW = '''<Window {ns}
        Title="Clear Warnings by Netbuild" Width="980" Height="820" MinWidth="820" MinHeight="560"
        WindowStartupLocation="CenterScreen" FontFamily="Segoe UI" FontSize="12" ShowInTaskbar="False">
  <DockPanel Margin="10">
    <StackPanel DockPanel.Dock="Top">
      <TextBlock x:Name="model_tb" FontWeight="Bold" FontSize="13"/>
      <TextBlock x:Name="profile_tb" Margin="0,4,0,0" TextWrapping="Wrap"/>
    </StackPanel>
    <GroupBox DockPanel.Dock="Top" Margin="0,8,0,0" Header="Steps -- run in this order, each one optional">
      <StackPanel Margin="6">{steps}
        <TextBlock Foreground="#B26A00" Margin="0,4,0,0" TextWrapping="Wrap"
                   Text="Steps 1 - 3 delete EVERY Area Plan, Area schedule, Area and Area Separation Line in this model."/>
      </StackPanel>
    </GroupBox>
    <WrapPanel DockPanel.Dock="Top" Margin="0,8,0,0">
      <TextBlock Text="Step 6 Type Mark prefixes (keyword=PREFIX; ...)" VerticalAlignment="Center" Margin="0,0,6,0"/>
      <TextBox x:Name="rules_tb" Width="300"/>
    </WrapPanel>
    <WrapPanel DockPanel.Dock="Top" Margin="0,8,0,0">
      <Button x:Name="summary_btn" Content="Warnings summary" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="dry_btn" Content="1. Dry run (nothing changes)" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="run_btn" Content="2. Run" Padding="10,3" Margin="0,0,20,0" FontWeight="Bold"/>
      <Button x:Name="copy_btn" Content="Copy report" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="logs_btn" Content="Open logs folder" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="about_btn" Content="About" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="close_btn" Content="Close" Padding="10,3"/>
    </WrapPanel>
    <TextBlock x:Name="status_tb" DockPanel.Dock="Top" Foreground="#555555" Margin="0,6,0,0" TextWrapping="Wrap"/>
    <ListBox x:Name="report_lb" Margin="0,6,0,0" FontFamily="Consolas" FontSize="11"
             ScrollViewer.HorizontalScrollBarVisibility="Auto"/>
  </DockPanel>
</Window>'''


def _xml(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def window_xaml():
    steps = "".join(_STEP.format(i=i, label=_xml(label)) for i, (_, label) in enumerate(STEPS))
    return _WINDOW.format(ns=_NS, steps=steps)
